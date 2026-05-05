import type {
	FileKind,
	UploadResult,
	DonePayload,
	ExtractEvent,
	UploadProgress,
	ExtractedTable,
} from "./types";

export const DB_EXTENSIONS = new Set([
	"ib",
	"sqlite",
	"sqlite3",
	"db",
	"fdb",
	"gdb",
	"mdb",
	"accdb",
	"dbf",
]);

export const ACCEPT =
	".ib,.sqlite,.sqlite3,.db,.fdb,.gdb,.mdb,.accdb,.dbf,.csv,.tsv,.json,.jsonl,.ndjson,.sql,.xlsx,.xls,text/csv,application/json,application/sql";

// localStorage key prefixes — defined here so both UploadStage and TransformStage can import from one place
export const ACTIVE_EXTRACTION_LS_PREFIX = "etl_studio.active_extraction.";
export const ACTIVE_TRANSFORM_LS_PREFIX = "etl_studio.active_transform.";

export function detectKind(name: string): FileKind {
	const ext = name.toLowerCase().split(".").pop() ?? "";
	if (ext === "csv") return "csv";
	if (ext === "tsv") return "tsv";
	if (["json", "jsonl", "ndjson"].includes(ext)) return "json";
	if (ext === "sql") return "sql";
	if (["xlsx", "xls"].includes(ext)) return "xlsx";
	if (ext === "ib") return "ib";
	if (["sqlite", "sqlite3", "db"].includes(ext)) return "sqlite";
	return "unknown";
}

export function isDbFile(name: string): boolean {
	const ext = name.toLowerCase().split(".").pop() ?? "";
	return DB_EXTENSIONS.has(ext);
}

export function fmtSize(n: number): string {
	if (n < 1024) return n + " B";
	if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
	if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
	return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

// We're in the "uploading bytes" phase iff progress is non-null AND we
// haven't reached 100% yet. Once 100% is reached, the backend has the
// file and we hand off to the extraction phase.
export function _isUploadingPhase(p: UploadProgress | null): boolean {
	if (!p) return false;
	if (p.total === 0) return true;
	return p.loaded < p.total;
}

export function donePayloadToUploadResult(data: DonePayload): UploadResult {
	const tables: ExtractedTable[] = (data.tables_extracted ?? []).map((name: string) => ({
		name,
		rowCount: data.stats?.[name]?.row_count ?? 0,
		colCount: Object.keys(data.inferred_schema?.[name] ?? {}).length,
		columns: Object.keys(data.inferred_schema?.[name] ?? {}),
	}));
	return {
		sessionId: data.session_id,
		tables,
		preview: data.preview ?? {},
		schema: data.inferred_schema ?? {},
		stats: data.stats ?? {},
		excludedTables: [],
		selectedEntities: [],
	};
}

// Drains an NDJSON event stream from /api/extract/{sid}/stream. Calls
// onEvent for every progress event, returns the final 'done' payload.
// Throws if the stream ends with an 'error' event or no terminal event
// arrives.
export async function consumeExtractStream(
	sessionId: string,
	onEvent?: (event: ExtractEvent) => void,
	signal?: AbortSignal,
): Promise<DonePayload> {
	const res = await fetch(`/api/extract/${sessionId}/stream`, { signal });
	if (!res.ok || !res.body) {
		const err = await res.json().catch(() => null);
		throw new Error(err?.detail || `Stream failed (HTTP ${res.status})`);
	}
	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	let finalPayload: DonePayload | null = null;
	let streamError: string | null = null;

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		let nl: number;
		while ((nl = buffer.indexOf("\n")) >= 0) {
			const line = buffer.slice(0, nl).trim();
			buffer = buffer.slice(nl + 1);
			if (!line) continue;
			let evt: { event: string; [k: string]: unknown };
			try {
				evt = JSON.parse(line);
			} catch {
				continue;
			}
			if (evt.event === "error") {
				streamError = String(evt.message ?? "Extraction failed");
				break;
			}
			if (evt.event === "done") {
				const { event: _e, ...rest } = evt;
				finalPayload = rest as unknown as DonePayload;
				if (onEvent) onEvent(evt as unknown as ExtractEvent);
			} else if (onEvent) {
				onEvent(evt as unknown as ExtractEvent);
			}
		}
		if (streamError) break;
	}

	if (streamError) throw new Error(streamError);
	if (!finalPayload) throw new Error("Stream ended without a final result");
	return finalPayload;
}

// fetch() doesn't expose upload progress — XMLHttpRequest does. Wrap it
// in a fetch-shaped Promise<Response> so callers stay simple.
export function xhrUpload(
	url: string,
	body: FormData,
	options: {
		onProgress?: (p: UploadProgress) => void;
		signal?: AbortSignal;
	} = {},
): Promise<Response> {
	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		xhr.open("POST", url);
		if (options.onProgress) {
			xhr.upload.onprogress = (e) => {
				if (e.lengthComputable) {
					options.onProgress!({ loaded: e.loaded, total: e.total });
				}
			};
		}
		xhr.onload = () => {
			const headers = new Headers();
			const ct = xhr.getResponseHeader("Content-Type");
			if (ct) headers.set("Content-Type", ct);
			resolve(
				new Response(xhr.responseText, {
					status: xhr.status,
					statusText: xhr.statusText,
					headers,
				}),
			);
		};
		xhr.onerror = () => reject(new Error("Network error"));
		xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
		if (options.signal) {
			if (options.signal.aborted) {
				xhr.abort();
				return;
			}
			options.signal.addEventListener("abort", () => xhr.abort());
		}
		xhr.send(body);
	});
}

export async function uploadToBackend(
	files: File[],
	projectId: string | null,
	password?: string,
	onEvent?: (event: ExtractEvent) => void,
	onSessionReady?: (sessionId: string) => void,
	signal?: AbortSignal,
	onUploadProgress?: (p: UploadProgress) => void,
): Promise<UploadResult> {
	// If any file is a DB file, use the two-phase endpoints:
	//   1. POST /api/upload-db          (sync — returns session_id once file is on disk)
	//   2. POST /api/extract/{sid}      (returns immediately; extraction runs in background)
	//   3. GET  /api/extract/{sid}/stream  (NDJSON with full replay)
	const dbFile = files.find((f) => isDbFile(f.name));
	if (dbFile) {
		// Step 1 — upload
		const uploadForm = new FormData();
		uploadForm.append("file", dbFile);
		if (projectId) uploadForm.append("project_id", projectId);
		const upRes = await xhrUpload("/api/upload-db", uploadForm, {
			onProgress: onUploadProgress,
			signal,
		});
		if (!upRes.ok) {
			const err = await upRes.json().catch(() => null);
			throw new Error(err?.detail || `Upload failed (HTTP ${upRes.status})`);
		}
		const upData = (await upRes.json()) as { session_id: string };
		const sessionId = upData.session_id;
		if (onSessionReady) onSessionReady(sessionId);

		// Step 2 — kick off extraction (returns immediately)
		const extractForm = new FormData();
		if (password) extractForm.append("password", password);
		const exRes = await fetch(`/api/extract/${sessionId}`, {
			method: "POST",
			body: extractForm,
			signal,
		});
		if (!exRes.ok) {
			const err = await exRes.json().catch(() => null);
			throw new Error(err?.detail || `Extract failed (HTTP ${exRes.status})`);
		}

		// Step 3 — stream events with replay
		const data = await consumeExtractStream(sessionId, onEvent, signal);
		return donePayloadToUploadResult(data);
	}

	// Flat files — use /api/upload
	const form = new FormData();
	for (const f of files) form.append("files", f);
	if (projectId) form.append("project_id", projectId);
	const res = await xhrUpload("/api/upload", form, {
		onProgress: onUploadProgress,
		signal,
	});
	if (!res.ok) {
		const err = await res.json().catch(() => null);
		throw new Error(err?.detail || "Upload failed");
	}
	const data = await res.json();
	const schema: Record<string, Record<string, unknown>> = data.inferred_schema ?? {};
	const stats: Record<string, { row_count: number }> = data.stats ?? {};
	const tables: ExtractedTable[] = Object.keys(schema).map((name) => ({
		name,
		rowCount: stats[name]?.row_count ?? 0,
		colCount: Object.keys(schema[name] ?? {}).length,
		columns: Object.keys(schema[name] ?? {}),
	}));
	return {
		sessionId: data.session_id,
		tables,
		preview: data.preview ?? {},
		schema,
		stats,
		excludedTables: [],
		selectedEntities: [],
	};
}
