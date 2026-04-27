import {
	createContext,
	useContext,
	useEffect,
	useMemo,
	useRef,
	useState,
	type ChangeEvent,
	type DragEvent,
	type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { RL_STAGES, type Project, type ResumedSession, type StageId } from "./data";
import { IArrow, ICheck, IDisk, IUpload, IX } from "./icons";
import { RlTopbar } from "./Topbar";
import { RlPromptModal } from "./PromptModal";

// ---------- types ----------

type FileKind = "csv" | "tsv" | "json" | "sql" | "xlsx" | "ib" | "sqlite" | "unknown";

const DB_EXTENSIONS = new Set(["ib", "sqlite", "sqlite3", "db", "fdb", "gdb", "mdb", "accdb", "dbf"]);

type StagedFile = {
	file: File;
	kind: FileKind;
};

type ExtractedTable = {
	name: string;
	rowCount: number;
	colCount: number;
	columns: string[];
};

type UploadResult = {
	sessionId: string;
	tables: ExtractedTable[];
	preview: Record<string, Record<string, unknown>[]>;
	schema: Record<string, Record<string, unknown>>;
	stats: Record<string, { row_count: number }>;
	excludedTables: string[];
};

type TransformResult = {
	ok: boolean;
	tables_transformed: number;
	total_rows: number;
	encoding_conversions: number;
	type_conversions: number;
	reference_mappings: number;
	null_normalizations: number;
	warnings: string[];
	exceptions?: Record<string, unknown[]>;
	preview: Record<string, unknown>;
};

type LoadResult = {
	ok: boolean;
	output_files: string[];
	rows_written: Record<string, number>;
	errors: string[];
	exceptions_written?: string[];
};

type PipelineCtx = {
	projectId: string | null;
	staged: StagedFile[];
	addStaged: (files: StagedFile[]) => void;
	removeStaged: (idx: number) => void;
	clearStaged: () => void;
	uploadResult: UploadResult | null;
	setUploadResult: (r: UploadResult | null) => void;
	transformResult: TransformResult | null;
	setTransformResult: (r: TransformResult | null) => void;
	loadResult: LoadResult | null;
	setLoadResult: (r: LoadResult | null) => void;
};

const PipelineContext = createContext<PipelineCtx | null>(null);

function usePipelineCtx(): PipelineCtx {
	const ctx = useContext(PipelineContext);
	if (!ctx) throw new Error("PipelineContext not found");
	return ctx;
}

function PipelineProvider({
	projectId,
	resumed,
	children,
}: {
	projectId: string | null;
	resumed: ResumedSession | null;
	children: ReactNode;
}) {
	const [staged, setStaged] = useState<StagedFile[]>([]);
	const [uploadResult, setUploadResult] = useState<UploadResult | null>(() => {
		if (!resumed) return null;
		// Prefer the full extracted set so excluded tables remain visible
		// when the user revisits the extract stage.
		const tableNames = resumed.allExtractedTables?.length
			? resumed.allExtractedTables
			: resumed.tables.length > 0
				? resumed.tables
				: Object.keys(resumed.schema);
		if (tableNames.length === 0) return null;
		return {
			sessionId: resumed.sessionId,
			tables: tableNames.map((name) => ({
				name,
				rowCount: resumed.stats[name]?.row_count ?? 0,
				colCount: Object.keys(resumed.schema[name] ?? {}).length,
				columns: Object.keys(resumed.schema[name] ?? {}),
			})),
			preview: resumed.preview as Record<string, Record<string, unknown>[]>,
			schema: resumed.schema,
			stats: resumed.stats,
			excludedTables: resumed.excludedTables ?? [],
		};
	});
	const [transformResult, setTransformResult] = useState<TransformResult | null>(() => {
		if (!resumed?.transform) return null;
		const t = resumed.transform as Record<string, unknown>;
		return {
			ok: t.ok as boolean ?? true,
			tables_transformed: t.tables_transformed as number ?? 0,
			total_rows: t.total_rows as number ?? 0,
			encoding_conversions: t.encoding_conversions as number ?? 0,
			type_conversions: t.type_conversions as number ?? 0,
			reference_mappings: t.reference_mappings as number ?? 0,
			null_normalizations: t.null_normalizations as number ?? 0,
			warnings: (t.warnings as string[]) ?? [],
			preview: (t.preview as Record<string, unknown>) ?? {},
		};
	});
	const [loadResult, setLoadResult] = useState<LoadResult | null>(() => {
		if (!resumed?.loadResult) return null;
		const l = resumed.loadResult as Record<string, unknown>;
		return {
			ok: l.ok as boolean ?? true,
			output_files: (l.output_files as string[]) ?? [],
			rows_written: (l.rows_written as Record<string, number>) ?? {},
			errors: (l.errors as string[]) ?? [],
		};
	});
	const ctx: PipelineCtx = {
		projectId,
		staged,
		addStaged: (files) => setStaged((prev) => [...prev, ...files]),
		removeStaged: (idx) => setStaged((prev) => prev.filter((_, i) => i !== idx)),
		clearStaged: () => setStaged([]),
		uploadResult,
		setUploadResult,
		transformResult,
		setTransformResult,
		loadResult,
		setLoadResult,
	};
	return (
		<PipelineContext.Provider value={ctx}>{children}</PipelineContext.Provider>
	);
}

// ---------- helpers ----------

const ACCEPT =
	".ib,.sqlite,.sqlite3,.db,.fdb,.gdb,.mdb,.accdb,.dbf,.csv,.tsv,.json,.jsonl,.ndjson,.sql,.xlsx,.xls,text/csv,application/json,application/sql";

function detectKind(name: string): FileKind {
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

function isDbFile(name: string): boolean {
	const ext = name.toLowerCase().split(".").pop() ?? "";
	return DB_EXTENSIONS.has(ext);
}

function fmtSize(n: number): string {
	if (n < 1024) return n + " B";
	if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
	if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
	return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

type ExtractEvent =
	| { event: "listing" }
	| { event: "start"; tables: string[] }
	| { event: "table_done"; name: string; rows: number; index: number; total: number }
	| { event: "done"; [k: string]: unknown }
	| { event: "error"; message: string };

type DonePayload = {
	session_id: string;
	tables_extracted?: string[];
	preview?: Record<string, Record<string, unknown>[]>;
	inferred_schema?: Record<string, Record<string, unknown>>;
	stats?: Record<string, { row_count: number }>;
};

function donePayloadToUploadResult(data: DonePayload): UploadResult {
	const tables: ExtractedTable[] = (data.tables_extracted ?? []).map(
		(name: string) => ({
			name,
			rowCount: data.stats?.[name]?.row_count ?? 0,
			colCount: Object.keys(data.inferred_schema?.[name] ?? {}).length,
			columns: Object.keys(data.inferred_schema?.[name] ?? {}),
		}),
	);
	return {
		sessionId: data.session_id,
		tables,
		preview: data.preview ?? {},
		schema: data.inferred_schema ?? {},
		stats: data.stats ?? {},
		excludedTables: [],
	};
}

// Drains an NDJSON event stream from /api/extract/{sid}/stream. Calls
// onEvent for every progress event, returns the final 'done' payload.
// Throws if the stream ends with an 'error' event or no terminal event
// arrives.
async function consumeExtractStream(
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

async function uploadToBackend(
	files: File[],
	projectId: string | null,
	password?: string,
	onEvent?: (event: ExtractEvent) => void,
	onSessionReady?: (sessionId: string) => void,
	signal?: AbortSignal,
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
		const upRes = await fetch("/api/upload-db", { method: "POST", body: uploadForm, signal });
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
	const res = await fetch("/api/upload", { method: "POST", body: form, signal });
	if (!res.ok) {
		const err = await res.json().catch(() => null);
		throw new Error(err?.detail || "Upload failed");
	}
	const data = await res.json();
	const schema: Record<string, Record<string, unknown>> =
		data.inferred_schema ?? {};
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
	};
}

// ---------- stepper ----------

function RlStepper({
	stage,
	onStage,
}: {
	stage: StageId;
	onStage: (s: StageId) => void;
}) {
	const idx = RL_STAGES.findIndex((s) => s.id === stage);
	return (
		<div className="steprail">
			{RL_STAGES.map((s, i) => (
				<div
					key={s.id}
					className={`step ${s.id === stage ? "active" : ""} ${i < idx ? "done" : ""}`}
					onClick={() => onStage(s.id)}
				>
					<div className="num">{i < idx ? "✓" : i + 1}</div>
					<div>
						<div>{s.label}</div>
						<div
							style={{
								fontFamily: "var(--lg-mono)",
								fontSize: 9,
								opacity: 0.7,
								textTransform: "none",
								letterSpacing: 0,
							}}
						>
							{s.sub}
						</div>
					</div>
				</div>
			))}
		</div>
	);
}

// ---------- upload ----------

function kindBadge(kind: FileKind) {
	const label = kind.toUpperCase();
	const cls =
		kind === "unknown"
			? "badge badge-err"
			: kind === "ib" || kind === "sqlite"
				? "badge badge-solid"
				: "badge badge-ok";
	return <span className={cls}>{label}</span>;
}

const DEFAULT_IB_PASSWORDS = ["masterkey", "AshSMSsw"];
const PASSWORDS_LS_KEY = "etl_studio.ib_known_passwords";
const NO_PASSWORD = "__none__";

const ACTIVE_EXTRACTION_LS_PREFIX = "etl_studio.active_extraction.";
// Sibling marker for the transform stage. Same shape as the extraction
// one: localStorage key is `{prefix}{projectId}` and the value carries the
// session id so the navbar dock can poll /api/transform/{sid}/status.
// Topbar.tsx scans for keys starting with this prefix.
const ACTIVE_TRANSFORM_LS_PREFIX = "etl_studio.active_transform.";

type ActiveExtraction = {
	sessionId: string;
	projectId: string | null;
	filename: string;
	startedAt: string;
};

function activeExtractionKey(projectId: string | null): string {
	return `${ACTIVE_EXTRACTION_LS_PREFIX}${projectId ?? "guest"}`;
}

function saveActiveExtraction(info: ActiveExtraction) {
	try {
		localStorage.setItem(activeExtractionKey(info.projectId), JSON.stringify(info));
	} catch {
		// ignore
	}
}

function loadActiveExtraction(projectId: string | null): ActiveExtraction | null {
	try {
		const raw = localStorage.getItem(activeExtractionKey(projectId));
		if (!raw) return null;
		return JSON.parse(raw) as ActiveExtraction;
	} catch {
		return null;
	}
}

function clearActiveExtraction(projectId: string | null) {
	try {
		localStorage.removeItem(activeExtractionKey(projectId));
	} catch {
		// ignore
	}
}

function loadKnownIbPasswords(): string[] {
	try {
		const raw = localStorage.getItem(PASSWORDS_LS_KEY);
		const merged = [...DEFAULT_IB_PASSWORDS];
		if (raw) {
			const parsed = JSON.parse(raw);
			if (Array.isArray(parsed)) {
				for (const v of parsed) {
					if (typeof v === "string" && v && !merged.includes(v)) merged.push(v);
				}
			}
		}
		return merged;
	} catch {
		return [...DEFAULT_IB_PASSWORDS];
	}
}

function saveKnownIbPasswords(list: string[]) {
	const custom = list.filter((p) => !DEFAULT_IB_PASSWORDS.includes(p));
	localStorage.setItem(PASSWORDS_LS_KEY, JSON.stringify(custom));
}

function RlUpload({ onNext }: { onNext: () => void }) {
	const { staged, addStaged, removeStaged, clearStaged, projectId, setUploadResult } =
		usePipelineCtx();
	const inputRef = useRef<HTMLInputElement | null>(null);
	const [uploading, setUploading] = useState(false);
	const [dragOver, setDragOver] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const [knownPasswords, setKnownPasswords] = useState<string[]>(() =>
		loadKnownIbPasswords(),
	);
	const [selectedPassword, setSelectedPassword] = useState<string>(
		DEFAULT_IB_PASSWORDS[0],
	);
	const [addingNew, setAddingNew] = useState(false);
	const [newPassword, setNewPassword] = useState("");

	const [extractStatus, setExtractStatus] = useState<string>("");
	const [allTables, setAllTables] = useState<string[]>([]);
	const [doneTables, setDoneTables] = useState<
		{ name: string; rows: number }[]
	>([]);
	const tableLogRef = useRef<HTMLDivElement | null>(null);
	const abortRef = useRef<AbortController | null>(null);
	const sessionRef = useRef<string | null>(null);
	const [cancelling, setCancelling] = useState(false);

	useEffect(() => {
		if (tableLogRef.current) {
			tableLogRef.current.scrollTop = tableLogRef.current.scrollHeight;
		}
	}, [doneTables.length]);

	const ingest = (files: FileList | File[] | null) => {
		if (!files) return;
		const arr = Array.from(files);
		if (arr.length === 0) return;
		const newFiles: StagedFile[] = arr.map((f) => ({
			file: f,
			kind: detectKind(f.name),
		}));
		setError(null);
		addStaged(newFiles);
	};

	const onInput = (e: ChangeEvent<HTMLInputElement>) => {
		ingest(e.target.files);
		e.target.value = "";
	};

	const onDragOver = (e: DragEvent) => {
		e.preventDefault();
		if (!dragOver) setDragOver(true);
	};
	const onDragLeave = () => setDragOver(false);
	const onDrop = (e: DragEvent) => {
		e.preventDefault();
		setDragOver(false);
		ingest(e.dataTransfer?.files ?? null);
	};

	const handleAddNewPassword = () => {
		const trimmed = newPassword.trim();
		if (!trimmed) {
			setAddingNew(false);
			setNewPassword("");
			return;
		}
		if (!knownPasswords.includes(trimmed)) {
			const next = [...knownPasswords, trimmed];
			setKnownPasswords(next);
			saveKnownIbPasswords(next);
		}
		setSelectedPassword(trimmed);
		setNewPassword("");
		setAddingNew(false);
	};

	const handleEvent = (evt: ExtractEvent) => {
		if (evt.event === "listing") {
			setExtractStatus("Listing tables…");
		} else if (evt.event === "start") {
			setAllTables(evt.tables);
			setExtractStatus(`Extracting ${evt.tables.length} tables…`);
		} else if (evt.event === "table_done") {
			setDoneTables((prev) => [
				...prev,
				{ name: evt.name, rows: evt.rows },
			]);
		}
	};

	const handleUpload = async () => {
		if (staged.length === 0) return;
		const ctrl = new AbortController();
		abortRef.current = ctrl;
		sessionRef.current = null;
		setCancelling(false);
		setUploading(true);
		setError(null);
		setExtractStatus("Uploading…");
		setAllTables([]);
		setDoneTables([]);
		const dbFile = staged.find((s) => isDbFile(s.file.name));
		try {
			const password =
				selectedPassword === NO_PASSWORD ? undefined : selectedPassword;
			const result = await uploadToBackend(
				staged.map((s) => s.file),
				projectId,
				password,
				handleEvent,
				(sid) => {
					sessionRef.current = sid;
					if (dbFile) {
						saveActiveExtraction({
							sessionId: sid,
							projectId,
							filename: dbFile.file.name,
							startedAt: new Date().toISOString(),
						});
					}
				},
				ctrl.signal,
			);
			clearActiveExtraction(projectId);
			setUploadResult(result);
			onNext();
		} catch (e) {
			clearActiveExtraction(projectId);
			const aborted =
				ctrl.signal.aborted ||
				(e instanceof DOMException && e.name === "AbortError") ||
				(e instanceof Error && e.message.toLowerCase().includes("abort"));
			if (aborted) {
				setError(null);
				setExtractStatus("");
			} else {
				setError(e instanceof Error ? e.message : "Upload failed");
			}
		} finally {
			abortRef.current = null;
			setUploading(false);
			setCancelling(false);
		}
	};

	const handleCancel = () => {
		if (!abortRef.current) return;
		setCancelling(true);
		setExtractStatus("Cancelling…");
		const sid = sessionRef.current;
		abortRef.current.abort();
		if (sid) {
			void fetch(`/api/extract/${sid}/cancel`, { method: "POST" }).catch(
				() => undefined,
			);
		}
		clearActiveExtraction(projectId);
	};

	// On mount: if a previous extraction for this project is still in flight
	// (or recently finished but never confirmed), reconnect to its event
	// stream rather than re-uploading. This handles the "navigate away,
	// come back" case.
	useEffect(() => {
		const active = loadActiveExtraction(projectId);
		if (!active) return;
		let cancelled = false;
		const reconnect = async () => {
			try {
				const statusRes = await fetch(`/api/extract/${active.sessionId}/status`);
				if (!statusRes.ok) {
					clearActiveExtraction(projectId);
					return;
				}
				const status = (await statusRes.json()) as {
					status: string;
					filename?: string;
					tables_total?: number;
					tables_done?: number;
				};
				if (status.status !== "extracting" && status.status !== "done") {
					clearActiveExtraction(projectId);
					return;
				}
				if (cancelled) return;
				setUploading(true);
				setError(null);
				setExtractStatus(
					status.status === "done"
						? "Loading completed extraction…"
						: `Resuming extraction of ${active.filename}…`,
				);
				setAllTables([]);
				setDoneTables([]);
				const data = await consumeExtractStream(active.sessionId, handleEvent);
				if (cancelled) return;
				clearActiveExtraction(projectId);
				setUploadResult(donePayloadToUploadResult(data));
				onNext();
			} catch (e) {
				if (!cancelled) {
					clearActiveExtraction(projectId);
					setError(
						e instanceof Error ? e.message : "Failed to resume extraction",
					);
				}
			} finally {
				if (!cancelled) setUploading(false);
			}
		};
		void reconnect();
		return () => {
			cancelled = true;
		};
		// We only want to attempt this once on mount.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const hasDbFile = staged.some((s) => isDbFile(s.file.name));
	const hasFlatFile = staged.some((s) => !isDbFile(s.file.name));

	return (
		<div
			style={{
				display: "grid",
				gridTemplateColumns: "1fr 320px",
				gap: 14,
				marginTop: 14,
			}}
		>
			<div className="panel">
				<div className="panel-head">
					<IUpload size={10} />{" "}
					{uploading ? "EXTRACTING DATABASE" : "UPLOAD DATA FILES"}
				</div>
				<div className="panel-body">
					{uploading ? (
						<div
							style={{
								padding: "32px 20px",
								textAlign: "center",
								display: "flex",
								flexDirection: "column",
								alignItems: "center",
								gap: 12,
							}}
						>
							<div className="sprite-disk" style={{ margin: "0 auto 4px" }} />
							<div
								className="pixel"
								style={{
									fontSize: 14,
									color: "var(--lg-amber)",
									letterSpacing: "0.15em",
								}}
							>
								{extractStatus || "EXTRACTION IN PROGRESS"}
							</div>
							{allTables.length > 0 ? (
								<>
									<div
										className="mono"
										style={{
											fontSize: 11,
											color: "var(--lg-ink-dim)",
										}}
									>
										{doneTables.length} OF {allTables.length} TABLES EXTRACTED
									</div>
									{doneTables.length < allTables.length && (
										<div
											className="mono"
											style={{
												fontSize: 11,
												color: "var(--lg-ink)",
											}}
										>
											→ {allTables[doneTables.length]}
										</div>
									)}
								</>
							) : (
								<div
									className="mono"
									style={{ fontSize: 11, color: "var(--lg-ink-mute)" }}
								>
									Connecting to database…
								</div>
							)}
							<div
								className="mono"
								style={{
									fontSize: 10,
									color: "var(--lg-ink-mute)",
									marginTop: 8,
									maxWidth: 360,
									lineHeight: 1.6,
								}}
							>
								Extraction continues server-side. You can leave this page and
								come back — progress is saved.
							</div>
						</div>
					) : (
						<div
							className={`rl-drop ${dragOver ? "dragover" : ""}`}
							onDragOver={onDragOver}
							onDragEnter={onDragOver}
							onDragLeave={onDragLeave}
							onDrop={onDrop}
							onClick={() => inputRef.current?.click()}
							role="button"
							tabIndex={0}
						>
							<div className="sprite-disk" style={{ margin: "0 auto 14px" }} />
							<div
								className="pixel"
								style={{ fontSize: 12, color: "var(--lg-amber)" }}
							>
								DROP FILES HERE
							</div>
							<div
								className="mono"
								style={{
									fontSize: 11,
									color: "var(--lg-ink-mute)",
									marginTop: 8,
								}}
							>
								.IB · .SQLITE · .CSV · .TSV · .JSON · .SQL · .XLSX
							</div>
							<button
								className="btn btn-primary"
								type="button"
								style={{ marginTop: 16 }}
								onClick={(e) => {
									e.stopPropagation();
									inputRef.current?.click();
								}}
							>
								BROWSE FILES
							</button>
							<input
								ref={inputRef}
								type="file"
								multiple
								accept={ACCEPT}
								onChange={onInput}
								style={{ display: "none" }}
							/>
						</div>
					)}

					{!uploading && staged.length > 0 && (
						<div style={{ marginTop: 16 }}>
							<div
								className="pixel"
								style={{
									fontSize: 10,
									color: "var(--lg-ink-dim)",
									letterSpacing: "0.1em",
									marginBottom: 8,
								}}
							>
								STAGED · {staged.length} FILE{staged.length === 1 ? "" : "S"}
							</div>
							<div
								style={{ display: "flex", flexDirection: "column", gap: 6 }}
							>
								{staged.map((s, i) => (
									<div key={s.file.name + i} className="rl-file-row">
										<IDisk size={12} />
										<div style={{ flex: 1, minWidth: 0 }}>
											<div style={{ fontSize: 12 }}>{s.file.name}</div>
											<div
												style={{
													fontSize: 10,
													color: "var(--lg-ink-mute)",
													marginTop: 2,
												}}
											>
												{fmtSize(s.file.size)}
											</div>
										</div>
										{kindBadge(s.kind)}
										<button
											className="link"
											style={{ fontSize: 10 }}
											onClick={() => removeStaged(i)}
											title="Remove"
										>
											<IX size={8} />
										</button>
									</div>
								))}
							</div>
							{staged.length > 1 && (
								<button
									className="btn btn-ghost"
									style={{ marginTop: 10, padding: "4px 10px", fontSize: 10 }}
									onClick={clearStaged}
								>
									CLEAR ALL
								</button>
							)}
						</div>
					)}

					{error && (
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-coral)",
								marginTop: 12,
							}}
						>
							{"> "}{error}
						</div>
					)}
				</div>
			</div>
			<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
				{!uploading && (
					<div className="panel">
						<div className="panel-head">READY TO UPLOAD</div>
						<div className="panel-body">
							{staged.length === 0 ? (
								<div
									className="mono"
									style={{ fontSize: 11, color: "var(--lg-ink-mute)" }}
								>
									Add files to begin.
								</div>
							) : (
								<>
									<div
										className="pixel"
										style={{ fontSize: 14, color: "var(--lg-amber)" }}
									>
										{staged.length} FILE{staged.length === 1 ? "" : "S"}
									</div>
									<div
										className="mono"
										style={{
											fontSize: 11,
											color: "var(--lg-ink-dim)",
											marginTop: 6,
										}}
									>
										{fmtSize(staged.reduce((a, s) => a + s.file.size, 0))}
									</div>
									{hasDbFile && hasFlatFile && (
										<div
											className="mono"
											style={{
												fontSize: 10,
												color: "var(--lg-coral)",
												marginTop: 8,
											}}
										>
											! MIXING DB AND FLAT FILES — ONLY THE DB FILE WILL BE
											EXTRACTED
										</div>
									)}
								</>
							)}
						</div>
					</div>
				)}

				{!uploading && hasDbFile && (
					<div className="panel">
						<div className="panel-head">DATABASE PASSWORD</div>
						<div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 8 }}>
							{addingNew ? (
								<div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
									<input
										type="text"
										value={newPassword}
										onChange={(e) => setNewPassword(e.target.value)}
										onKeyDown={(e) => {
											if (e.key === "Enter") {
												e.preventDefault();
												handleAddNewPassword();
											} else if (e.key === "Escape") {
												setAddingNew(false);
												setNewPassword("");
											}
										}}
										placeholder="New password"
										autoFocus
										style={{
											background: "var(--lg-bg-panel, #111)",
											border: "1px solid var(--lg-ink-dim, #555)",
											color: "var(--lg-ink, #ddd)",
											fontFamily: "var(--lg-mono)",
											fontSize: 12,
											padding: "6px 8px",
										}}
									/>
									<div style={{ display: "flex", gap: 6 }}>
										<button
											className="btn btn-primary"
											style={{ fontSize: 10, padding: "4px 10px", flex: 1 }}
											onClick={handleAddNewPassword}
										>
											SAVE
										</button>
										<button
											className="btn btn-ghost"
											style={{ fontSize: 10, padding: "4px 10px", flex: 1 }}
											onClick={() => {
												setAddingNew(false);
												setNewPassword("");
											}}
										>
											CANCEL
										</button>
									</div>
								</div>
							) : (
								<>
									<select
										value={selectedPassword}
										onChange={(e) => {
											if (e.target.value === "__add__") {
												setAddingNew(true);
											} else {
												setSelectedPassword(e.target.value);
											}
										}}
										style={{
											background: "var(--lg-bg-panel, #111)",
											border: "1px solid var(--lg-ink-dim, #555)",
											color: "var(--lg-ink, #ddd)",
											fontFamily: "var(--lg-mono)",
											fontSize: 12,
											padding: "6px 8px",
											width: "100%",
										}}
									>
										<option value={NO_PASSWORD}>(no password)</option>
										{knownPasswords.map((p) => (
											<option key={p} value={p}>
												{p}
											</option>
										))}
										<option value="__add__">+ Add new password…</option>
									</select>
									<div
										className="mono"
										style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}
									>
										Saved in your browser. Sent with the upload.
									</div>
								</>
							)}
						</div>
					</div>
				)}

				{uploading && (
					<div className="panel">
						<div className="panel-head">
							{extractStatus || "EXTRACTING"}
							{allTables.length > 0 && (
								<span
									style={{
										float: "right",
										fontFamily: "var(--lg-mono)",
										color: "var(--lg-amber)",
									}}
								>
									{doneTables.length}/{allTables.length}
								</span>
							)}
						</div>
						<div className="panel-body">
							{allTables.length > 0 && (
								<div
									style={{
										height: 4,
										background: "var(--lg-ink-dim, #333)",
										marginBottom: 10,
										position: "relative",
										overflow: "hidden",
									}}
								>
									<div
										style={{
											position: "absolute",
											top: 0,
											left: 0,
											bottom: 0,
											background: "var(--lg-amber, #f5b32a)",
											width: `${(doneTables.length / allTables.length) * 100}%`,
											transition: "width 120ms linear",
										}}
									/>
								</div>
							)}
							<div
								ref={tableLogRef}
								style={{
									maxHeight: 220,
									overflowY: "auto",
									fontFamily: "var(--lg-mono)",
									fontSize: 11,
									display: "flex",
									flexDirection: "column",
									gap: 2,
								}}
							>
								{doneTables.map((t) => (
									<div
										key={t.name}
										style={{ display: "flex", gap: 6, alignItems: "center" }}
									>
										<ICheck size={8} />
										<span style={{ flex: 1, color: "var(--lg-ink, #ddd)" }}>
											{t.name}
										</span>
										<span style={{ color: "var(--lg-ink-mute, #999)" }}>
											{t.rows.toLocaleString()}
										</span>
									</div>
								))}
								{allTables.length > 0 &&
									doneTables.length < allTables.length && (
										<div
											style={{
												display: "flex",
												gap: 6,
												alignItems: "center",
												color: "var(--lg-ink-mute, #999)",
											}}
										>
											<span style={{ width: 8 }}>›</span>
											<span style={{ flex: 1 }}>
												{allTables[doneTables.length]}…
											</span>
										</div>
									)}
								{doneTables.length === 0 && allTables.length === 0 && (
									<div style={{ color: "var(--lg-ink-mute, #999)" }}>
										{extractStatus}
									</div>
								)}
							</div>
						</div>
					</div>
				)}

				{uploading ? (
					<div style={{ display: "flex", gap: 8 }}>
						<button
							className="btn btn-primary"
							disabled
							style={{ flex: 1 }}
						>
							UPLOADING… <IArrow size={10} />
						</button>
						<button
							className="btn btn-ghost"
							onClick={handleCancel}
							disabled={cancelling}
							style={{ minWidth: 110 }}
						>
							{cancelling ? "CANCELLING…" : "CANCEL"} <IX size={10} />
						</button>
					</div>
				) : (
					<button
						className="btn btn-primary"
						disabled={staged.length === 0 || addingNew}
						onClick={handleUpload}
					>
						UPLOAD & EXTRACT <IArrow size={10} />
					</button>
				)}
			</div>
		</div>
	);
}

// ---------- table preview modal ----------

type PageData = {
	rows: Record<string, unknown>[];
	columns: string[];
	page: number;
	total_rows: number;
	total_pages: number;
};

function TablePreviewModal({
	sessionId,
	tableName,
	onClose,
}: {
	sessionId: string;
	tableName: string;
	onClose: () => void;
}) {
	const { uploadResult, setUploadResult } = usePipelineCtx();
	const [page, setPage] = useState(1);
	const [data, setData] = useState<PageData | null>(null);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [editing, setEditing] = useState(false);
	const [editedRows, setEditedRows] = useState<Record<string, unknown>[]>([]);
	const [saving, setSaving] = useState(false);
	const [dirty, setDirty] = useState(false);
	const [focusedRow, setFocusedRow] = useState(0);
	const [focusedCol, setFocusedCol] = useState(0);
	const focusedCellRef = useRef<HTMLTableCellElement | null>(null);

	const fetchPage = async (p: number) => {
		setLoading(true);
		setError(null);
		try {
			const res = await fetch(
				`/api/table-data/${sessionId}/${encodeURIComponent(tableName)}?page=${p}&page_size=100`,
			);
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || "Failed to load data");
			}
			const d = await res.json();
			setData(d);
			setPage(d.page);
			setEditedRows(d.rows.map((r: Record<string, unknown>) => ({ ...r })));
			setDirty(false);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Load failed");
		} finally {
			setLoading(false);
		}
	};

	const saveEdits = async () => {
		if (!data) return;
		setSaving(true);
		setError(null);
		try {
			// Fetch all rows, replace current page's rows, save back
			const allRes = await fetch(`/api/table-data/${sessionId}`);
			if (!allRes.ok) throw new Error("Failed to load full data");
			const allData = await allRes.json();
			const allRows: Record<string, unknown>[] = allData.tables[tableName] ?? [];
			const start = (page - 1) * 100;
			for (let i = 0; i < editedRows.length; i++) {
				allRows[start + i] = editedRows[i];
			}
			const res = await fetch(`/api/table-data/${sessionId}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ tables: { [tableName]: allRows } }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || "Save failed");
			}
			const saveData = await res.json();
			setDirty(false);

			// Propagate updated data to pipeline context
			if (uploadResult && saveData.preview && saveData.schema) {
				const updatedTables = uploadResult.tables.map((t) => ({
					...t,
					rowCount: saveData.stats?.[t.name]?.row_count ?? t.rowCount,
					colCount: Object.keys(saveData.schema[t.name] ?? {}).length || t.colCount,
					columns: Object.keys(saveData.schema[t.name] ?? {}).length > 0
						? Object.keys(saveData.schema[t.name])
						: t.columns,
				}));
				setUploadResult({
					...uploadResult,
					tables: updatedTables,
					schema: saveData.schema,
					stats: saveData.stats,
					preview: saveData.preview,
				});
			}

			// Refresh the current page
			await fetchPage(page);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Save failed");
		} finally {
			setSaving(false);
		}
	};

	const updateCell = (rowIdx: number, col: string, value: string) => {
		setEditedRows((prev) => {
			const next = [...prev];
			next[rowIdx] = { ...next[rowIdx], [col]: value || null };
			return next;
		});
		setDirty(true);
	};

	useEffect(() => {
		fetchPage(1);
	}, [sessionId, tableName]);

	const totalPages = data?.total_pages ?? 1;
	const displayRows = editing ? editedRows : (data?.rows ?? []);

	// Reset focus when page or data changes
	useEffect(() => {
		setFocusedRow(0);
		setFocusedCol(0);
	}, [page, tableName]);

	// Clamp focus when rows/cols shrink
	useEffect(() => {
		const colCount = data?.columns.length ?? 0;
		const rowCount = displayRows.length;
		setFocusedRow((r) => Math.max(0, Math.min(r, rowCount - 1)));
		setFocusedCol((c) => Math.max(0, Math.min(c, colCount - 1)));
	}, [displayRows.length, data?.columns.length]);

	// Keep focused cell scrolled into view
	useEffect(() => {
		focusedCellRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
	}, [focusedRow, focusedCol]);

	// Keyboard navigation. Uses capture phase + stopPropagation so the
	// modal swallows keys before any parent (e.g. RlExtract's window
	// listener) can react to them.
	useEffect(() => {
		const handler = (e: KeyboardEvent) => {
			const tag = (e.target as HTMLElement).tagName;
			const isInputFocused = tag === "INPUT" || tag === "TEXTAREA";

			// Allow inputs to handle their own keys, except Escape to cancel edit
			if (isInputFocused) {
				if (e.key === "Escape") {
					e.preventDefault();
					e.stopPropagation();
					(e.target as HTMLElement).blur();
				}
				return;
			}

			const cols = data?.columns.length ?? 0;
			const rowCount = displayRows.length;
			let handled = true;

			switch (e.key) {
				case "ArrowUp":
					setFocusedRow((r) => Math.max(0, r - 1));
					break;
				case "ArrowDown":
					setFocusedRow((r) => Math.min(rowCount - 1, r + 1));
					break;
				case "ArrowLeft":
					setFocusedCol((c) => Math.max(0, c - 1));
					break;
				case "ArrowRight":
					setFocusedCol((c) => Math.min(cols - 1, c + 1));
					break;
				case "Home":
					if (e.ctrlKey || e.metaKey) setFocusedRow(0);
					setFocusedCol(0);
					break;
				case "End":
					if (e.ctrlKey || e.metaKey) setFocusedRow(rowCount - 1);
					setFocusedCol(cols - 1);
					break;
				case "PageUp":
					if (page > 1) fetchPage(page - 1);
					break;
				case "PageDown":
					if (page < totalPages) fetchPage(page + 1);
					break;
				case "e":
				case "E":
					if (!editing) {
						setEditing(true);
					} else {
						setTimeout(() => {
							const input = focusedCellRef.current?.querySelector("input");
							input?.focus();
							input?.select();
						}, 0);
					}
					break;
				case "Enter":
					if (editing) {
						setTimeout(() => {
							const input = focusedCellRef.current?.querySelector("input");
							input?.focus();
							input?.select();
						}, 0);
					} else {
						handled = false;
					}
					break;
				case "x":
				case "X":
				case "Escape":
					if (editing) {
						setEditing(false);
						setEditedRows(data?.rows.map((r) => ({ ...r })) ?? []);
						setDirty(false);
					} else {
						onClose();
					}
					break;
				default:
					handled = false;
			}

			if (handled) {
				e.preventDefault();
				e.stopPropagation();
			}
		};
		document.addEventListener("keydown", handler, true);
		return () => document.removeEventListener("keydown", handler, true);
	}, [data, displayRows.length, page, totalPages, editing, onClose]);

	// Render into a portal at document.body so no ancestor's overflow,
	// transform, or stacking context can clip or hide the modal.
	return createPortal(
		<div
			style={{
				position: "fixed",
				top: 0,
				left: 0,
				right: 0,
				bottom: 0,
				zIndex: 99999,
				background: "rgba(0,0,0,0.78)",
				display: "grid",
				placeItems: "center",
				padding: 24,
			}}
			onClick={onClose}
		>
			<div
				style={{
					background: "var(--lg-bg)",
					border: `2px solid ${editing ? "var(--lg-coral)" : "var(--lg-amber)"}`,
					boxShadow: "0 12px 40px rgba(0,0,0,0.65)",
					width: "min(1200px, 92vw)",
					height: "min(720px, 86vh)",
					minHeight: 320,
					display: "flex",
					flexDirection: "column",
					overflow: "hidden",
					color: "var(--lg-ink)",
				}}
				onClick={(e) => e.stopPropagation()}
			>
				{/* Header */}
				<div
					style={{
						display: "flex",
						alignItems: "center",
						justifyContent: "space-between",
						padding: "10px 14px",
						borderBottom: "1px solid var(--lg-border)",
						background: "var(--lg-bg-2)",
					}}
				>
					<div style={{ display: "flex", alignItems: "center", gap: 10 }}>
						<IDisk size={10} />
						<span
							className="pixel"
							style={{ fontSize: 11, color: "var(--lg-amber)", letterSpacing: "0.1em" }}
						>
							{tableName.toUpperCase()}
						</span>
						{editing && (
							<span className="badge badge-warn">EDIT MODE</span>
						)}
						{data && (
							<span
								className="mono"
								style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}
							>
								{data.total_rows.toLocaleString()} rows · {data.columns.length} cols
							</span>
						)}
					</div>
					<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
						{editing ? (
							<>
								{dirty && (
									<button
										className="btn btn-primary"
										style={{ padding: "4px 10px", fontSize: 10 }}
										onClick={saveEdits}
										disabled={saving}
									>
										{saving ? "SAVING…" : "SAVE"}
									</button>
								)}
								<button
									className="btn btn-ghost"
									style={{ padding: "4px 10px", fontSize: 10 }}
									onClick={() => {
										setEditing(false);
										setEditedRows(data?.rows.map((r) => ({ ...r })) ?? []);
										setDirty(false);
									}}
								>
									CANCEL
								</button>
							</>
						) : (
							<button
								className="btn btn-ghost"
								style={{ padding: "4px 10px", fontSize: 10 }}
								onClick={() => setEditing(true)}
							>
								EDIT
							</button>
						)}
						<button
							className="link"
							style={{ fontSize: 12, color: "var(--lg-ink-mute)" }}
							onClick={onClose}
						>
							<IX size={10} /> CLOSE
						</button>
					</div>
				</div>

				{/* Table content */}
				<div style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
					{loading ? (
						<div
							className="pixel"
							style={{
								fontSize: 11,
								color: "var(--lg-amber)",
								letterSpacing: "0.1em",
								padding: 40,
								textAlign: "center",
							}}
						>
							LOADING…
						</div>
					) : error ? (
						<div
							className="mono"
							style={{ fontSize: 11, color: "var(--lg-coral)", padding: 40, textAlign: "center" }}
						>
							{error}
						</div>
					) : data && displayRows.length > 0 ? (
						<table className="table" style={{ width: "100%" }}>
							<thead>
								<tr>
									<th
										style={{
											width: 50,
											fontFamily: "var(--lg-pixel)",
											fontSize: 8,
											color: "var(--lg-ink-mute)",
										}}
									>
										#
									</th>
									{data.columns.map((col) => (
										<th key={col}>{col}</th>
									))}
								</tr>
							</thead>
							<tbody>
								{displayRows.map((row, ri) => {
									const isFocusedRow = ri === focusedRow;
									return (
										<tr
											key={ri}
											style={{
												background: isFocusedRow ? "rgba(255, 191, 71, 0.08)" : undefined,
											}}
										>
											<td
												style={{
													fontFamily: "var(--lg-mono)",
													fontSize: 9,
													color: isFocusedRow ? "var(--lg-amber)" : "var(--lg-ink-mute)",
													fontWeight: isFocusedRow ? 700 : undefined,
												}}
											>
												{(page - 1) * 100 + ri + 1}
											</td>
											{data.columns.map((col, ci) => {
												const isFocusedCell = isFocusedRow && ci === focusedCol;
												const cellRef = isFocusedCell ? focusedCellRef : undefined;
												const focusStyle = isFocusedCell
													? {
															outline: "2px solid var(--lg-amber)",
															outlineOffset: -2,
															background: "rgba(255, 191, 71, 0.15)",
														}
													: undefined;
												return editing ? (
													<td
														key={col}
														ref={cellRef}
														style={{ padding: 0, ...focusStyle }}
														onClick={() => {
															setFocusedRow(ri);
															setFocusedCol(ci);
														}}
													>
														<input
															className="input"
															style={{
																fontSize: 11,
																padding: "4px 6px",
																width: "100%",
																border: "none",
																borderBottom: "1px solid var(--lg-border)",
																background: "transparent",
															}}
															value={row[col] != null ? String(row[col]) : ""}
															onChange={(e) => updateCell(ri, col, e.target.value)}
															onFocus={() => {
																setFocusedRow(ri);
																setFocusedCol(ci);
															}}
														/>
													</td>
												) : (
													<td
														key={col}
														ref={cellRef}
														style={focusStyle}
														onClick={() => {
															setFocusedRow(ri);
															setFocusedCol(ci);
														}}
													>
														{row[col] != null ? String(row[col]) : "—"}
													</td>
												);
											})}
										</tr>
									);
								})}
							</tbody>
						</table>
					) : (
						<div
							className="mono"
							style={{ fontSize: 11, color: "var(--lg-ink-mute)", padding: 40, textAlign: "center" }}
						>
							No data in this table.
						</div>
					)}
				</div>

				{/* Pagination footer */}
				<div
					style={{
						display: "flex",
						alignItems: "center",
						justifyContent: "space-between",
						padding: "8px 14px",
						borderTop: "1px solid var(--lg-border)",
						background: "var(--lg-bg-2)",
					}}
				>
					<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-mute)", display: "flex", flexDirection: "column", gap: 2 }}>
						<div>
							PAGE {page} / {totalPages}
							{data && (
								<>
									{" · "}SHOWING {(page - 1) * 100 + 1}–
									{Math.min(page * 100, data.total_rows)} OF{" "}
									{data.total_rows.toLocaleString()}
								</>
							)}
						</div>
						<div style={{ fontSize: 9, color: "var(--lg-ink-faint)" }}>
							<span style={{ color: "var(--lg-amber)" }}>↑↓←→</span> NAV ·{" "}
							<span style={{ color: "var(--lg-amber)" }}>E</span> EDIT ·{" "}
							<span style={{ color: "var(--lg-amber)" }}>X</span>/<span style={{ color: "var(--lg-amber)" }}>ESC</span> CLOSE ·{" "}
							<span style={{ color: "var(--lg-amber)" }}>PGUP/PGDN</span> PAGE
						</div>
					</div>
					<div style={{ display: "flex", gap: 6 }}>
						<button
							className="btn btn-ghost"
							style={{ padding: "4px 10px", fontSize: 10 }}
							disabled={page <= 1 || loading}
							onClick={() => fetchPage(1)}
						>
							«
						</button>
						<button
							className="btn btn-ghost"
							style={{ padding: "4px 10px", fontSize: 10 }}
							disabled={page <= 1 || loading}
							onClick={() => fetchPage(page - 1)}
						>
							‹ PREV
						</button>
						<button
							className="btn btn-ghost"
							style={{ padding: "4px 10px", fontSize: 10 }}
							disabled={page >= totalPages || loading}
							onClick={() => fetchPage(page + 1)}
						>
							NEXT ›
						</button>
						<button
							className="btn btn-ghost"
							style={{ padding: "4px 10px", fontSize: 10 }}
							disabled={page >= totalPages || loading}
							onClick={() => fetchPage(totalPages)}
						>
							»
						</button>
					</div>
				</div>
			</div>
		</div>,
		document.body,
	);
}

// ---------- extract ----------

function RlExtract({ onNext }: { onNext: () => void }) {
	const {
		uploadResult,
		setUploadResult,
		transformResult,
		setTransformResult,
		setLoadResult,
	} = usePipelineCtx();
	const [previewTable, setPreviewTable] = useState<string | null>(null);
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [search, setSearch] = useState("");
	const [focusIdx, setFocusIdx] = useState(0);

	const tables = uploadResult?.tables ?? [];
	const schema = uploadResult?.schema ?? {};
	const excludedSet = useMemo(
		() => new Set(uploadResult?.excludedTables ?? []),
		[uploadResult?.excludedTables],
	);

	const rows = useMemo(() => {
		return tables.map((t) => {
			const colTypes = Object.values(schema[t.name] ?? {}) as string[];
			const uniqueTypes = Array.from(
				new Set(
					colTypes.map((v) =>
						typeof v === "string" ? v.toUpperCase() : "TEXT",
					),
				),
			);
			return {
				n: t.name,
				r: t.rowCount,
				c: t.colCount,
				types: uniqueTypes.length > 0 ? uniqueTypes.slice(0, 4) : ["TEXT"],
			};
		});
	}, [tables, schema]);

	// Selection state, keyed by table name so it survives re-orderings.
	// Initial pick state honours any tables that were previously excluded
	// (e.g. when the user navigates back to the extract stage from a later
	// stage).
	const [picked, setPicked] = useState<Record<string, boolean>>(() =>
		Object.fromEntries(tables.map((t) => [t.name, !excludedSet.has(t.name)])),
	);

	// If tables change (new extraction) or excluded set changes, re-sync.
	useEffect(() => {
		setPicked((prev) => {
			const next: Record<string, boolean> = {};
			let same = Object.keys(prev).length === tables.length;
			for (const t of tables) {
				const defaultPicked = !excludedSet.has(t.name);
				next[t.name] = t.name in prev ? prev[t.name] : defaultPicked;
				if (!(t.name in prev)) same = false;
			}
			return same ? prev : next;
		});
	}, [tables, excludedSet]);

	const filtered = useMemo(() => {
		if (!search.trim()) return rows;
		const q = search.trim().toLowerCase();
		return rows.filter((r) => r.n.toLowerCase().includes(q));
	}, [rows, search]);

	useEffect(() => {
		const handleKeyDown = (e: KeyboardEvent) => {
			const target = e.target as HTMLElement;
			const isInput = target.tagName === "INPUT" || target.tagName === "TEXTAREA";
			if (isInput) return;

			switch (e.key.toLowerCase()) {
				case "arrowup":
					e.preventDefault();
					setFocusIdx((i) => Math.max(0, i - 1));
					break;
				case "arrowdown":
					e.preventDefault();
					setFocusIdx((i) => Math.min(filtered.length - 1, i + 1));
					break;
				case "d":
				case " ":
					if (filtered.length > 0 && focusIdx < filtered.length) {
						e.preventDefault();
						const tableName = filtered[focusIdx].n;
						togglePick(tableName);
					}
					break;
				case "p":
					if (filtered.length > 0 && focusIdx < filtered.length && uploadResult?.sessionId) {
						e.preventDefault();
						setPreviewTable(filtered[focusIdx].n);
					}
					break;
				case "e":
					e.preventDefault();
					deselectEmpty();
					break;
				case "a":
					e.preventDefault();
					toggleAllTables();
					break;
			}
		};
		window.addEventListener("keydown", handleKeyDown);
		return () => window.removeEventListener("keydown", handleKeyDown);
	}, [focusIdx, filtered, rows, uploadResult?.sessionId]);

	const pickedCount = rows.filter((r) => picked[r.n]).length;
	const pickedRowCount = rows.reduce(
		(a, r) => a + (picked[r.n] ? r.r : 0),
		0,
	);
	const emptyCount = rows.filter((r) => r.r === 0 && picked[r.n]).length;

	const togglePick = (name: string) =>
		setPicked((p) => ({ ...p, [name]: !p[name] }));

	const allFilteredPicked = filtered.every((r) => picked[r.n]);
	const toggleAllFiltered = () => {
		setPicked((p) => {
			const next = { ...p };
			const target = !allFilteredPicked;
			for (const r of filtered) next[r.n] = target;
			return next;
		});
	};

	const allTablesPicked = rows.every((r) => picked[r.n]);
	const toggleAllTables = () => {
		setPicked((p) => {
			const next = { ...p };
			const target = !allTablesPicked;
			for (const r of rows) next[r.n] = target;
			return next;
		});
	};

	const deselectEmpty = () => {
		setPicked((p) => {
			const next = { ...p };
			for (const r of rows) if (r.r === 0) next[r.n] = false;
			return next;
		});
	};

	const proceed = async () => {
		if (!uploadResult?.sessionId) return;
		const selectedNames = rows.filter((r) => picked[r.n]).map((r) => r.n);
		setSaving(true);
		setError(null);
		try {
			const res = await fetch(
				`/api/pre-extract-select/${uploadResult.sessionId}`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ tables: selectedNames }),
				},
			);
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || "Selection failed");
			}
			const data = (await res.json()) as {
				ok: boolean;
				changed: boolean;
				kept: string[];
				excluded: string[];
			};
			if (uploadResult) {
				setUploadResult({
					...uploadResult,
					excludedTables: data.excluded,
				});
			}
			if (data.changed) {
				setTransformResult(null);
				setLoadResult(null);
			}
			onNext();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Selection failed");
		} finally {
			setSaving(false);
		}
	};

	return (
		<div
			style={{
				display: "grid",
				gridTemplateColumns: "1fr 320px",
				gap: 14,
				marginTop: 14,
			}}
		>
			{previewTable && uploadResult?.sessionId && (
				<TablePreviewModal
					sessionId={uploadResult.sessionId}
					tableName={previewTable}
					onClose={() => setPreviewTable(null)}
				/>
			)}
			<div className="panel">
				<div
					className="panel-head"
					style={{ display: "flex", alignItems: "center", gap: 12 }}
				>
					<IDisk size={10} />
					<span>
						EXTRACTED {tables.length} · {pickedCount} PICKED
					</span>
					<div style={{ flex: 1 }} />
					<input
						className="input"
						placeholder="Search…"
						value={search}
						onChange={(e) => setSearch(e.target.value)}
						style={{
							fontSize: 10,
							padding: "3px 8px",
							width: 160,
							background: "var(--lg-bg)",
							border: "1px solid var(--lg-border)",
							color: "var(--lg-ink)",
							fontFamily: "var(--lg-mono)",
							textTransform: "none",
							letterSpacing: 0,
						}}
					/>
					<button
						className="btn btn-ghost"
						style={{ padding: "3px 10px", fontSize: 9 }}
						onClick={toggleAllFiltered}
						disabled={filtered.length === 0}
					>
						{allFilteredPicked ? "DESELECT" : "SELECT"}{" "}
						{search ? "FILTERED" : "ALL"}
					</button>
				</div>
				<div className="panel-body" style={{ padding: 0 }}>
					{filtered.length === 0 ? (
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-mute)",
								padding: 30,
								textAlign: "center",
							}}
						>
							{rows.length === 0
								? "No tables extracted yet. Go back to Upload first."
								: `No tables match "${search}".`}
						</div>
					) : (
						<table className="table">
							<thead>
								<tr>
									<th style={{ width: 30 }}></th>
									<th>TABLE</th>
									<th>ROWS</th>
									<th>COLS</th>
									<th>TYPES</th>
									<th style={{ width: 70 }}></th>
								</tr>
							</thead>
							<tbody>
								{filtered.map((t, idx) => {
									const isPicked = !!picked[t.n];
										const isFocused = idx === focusIdx;
									return (
										<tr
											key={t.n}
											onClick={() => togglePick(t.n)}
											style={{ cursor: "pointer", background: isFocused ? "var(--lg-bg-2)" : undefined }}
											className={isPicked ? "row-selected" : ""}
										>
											<td>
												<div
													style={{
														width: 12,
														height: 12,
														border: "1px solid var(--lg-amber)",
														background: isPicked
															? "var(--lg-amber)"
															: "transparent",
														display: "flex",
														alignItems: "center",
														justifyContent: "center",
														color: "#0a0410",
													}}
												>
													{isPicked && <ICheck size={8} />}
												</div>
											</td>
											<td
												style={{
													fontFamily: "var(--lg-pixel)",
													fontSize: 9,
													color: "var(--lg-amber)",
													letterSpacing: "0.1em",
												}}
											>
												{t.n.toUpperCase()}
											</td>
											<td
												style={{
													fontVariantNumeric: "tabular-nums",
													color:
														t.r === 0 ? "var(--lg-ink-mute)" : undefined,
												}}
											>
												{t.r.toLocaleString()}
											</td>
											<td>{t.c}</td>
											<td>
												<div
													style={{ display: "flex", gap: 4, flexWrap: "wrap" }}
												>
													{t.types.map((tp) => (
														<span key={tp} className="badge badge-mute">
															{tp}
														</span>
													))}
												</div>
											</td>
											<td onClick={(e) => e.stopPropagation()}>
												<button
													className="btn btn-ghost"
													style={{ padding: "2px 8px", fontSize: 9 }}
													onClick={() => setPreviewTable(t.n)}
												>
													PREVIEW
												</button>
											</td>
										</tr>
									);
								})}
							</tbody>
						</table>
					)}
				</div>
			</div>
			<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">SELECTED</div>
					<div className="panel-body">
						<div
							className="pixel"
							style={{ fontSize: 28, color: "var(--lg-amber)" }}
						>
							{String(pickedCount).padStart(2, "0")} / {tables.length} TBLS
						</div>
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-dim)",
								marginTop: 4,
							}}
						>
							{pickedRowCount.toLocaleString()} ROWS
						</div>
					</div>
				</div>
				<div className="panel">
					<div className="panel-head">QUICK ACTIONS</div>
					<div
						className="panel-body"
						style={{ display: "flex", flexDirection: "column", gap: 8 }}
					>
						<button
							className="btn btn-ghost"
							style={{ fontSize: 10, padding: "6px 10px" }}
							onClick={deselectEmpty}
							disabled={emptyCount === 0}
							title="Uncheck every table that has zero rows"
						>
							DESELECT EMPTY ({emptyCount})
						</button>
						<div
							className="mono"
							style={{
								fontSize: 10,
								color: "var(--lg-ink-mute)",
								lineHeight: 1.6,
							}}
						>
							Click a row to toggle selection. Use Search to find tables.
							Preview shows the first 100 rows.
						</div>
					</div>
				</div>
				{(() => {
					const currentExcluded = new Set(
						rows.filter((r) => !picked[r.n]).map((r) => r.n),
					);
					const prevExcluded = excludedSet;
					let diff = currentExcluded.size !== prevExcluded.size;
					if (!diff) {
						for (const n of currentExcluded) {
							if (!prevExcluded.has(n)) {
								diff = true;
								break;
							}
						}
					}
					if (diff && transformResult) {
						return (
							<div
								className="mono"
								style={{
									fontSize: 10,
									padding: "8px 10px",
									border: "1px solid var(--lg-amber, #c79b00)",
									color: "var(--lg-amber, #c79b00)",
									lineHeight: 1.5,
								}}
							>
								{"> "}Changing the selection will reset transform & export
								results. Configure work for tables that remain selected is
								preserved.
							</div>
						);
					}
					return null;
				})()}
				{error && (
					<div
						className="mono"
						style={{ fontSize: 11, color: "var(--lg-coral)" }}
					>
						{"> "}
						{error}
					</div>
				)}
				<button
					className="btn btn-primary"
					onClick={proceed}
					disabled={pickedCount === 0 || saving}
				>
					{saving ? "SAVING…" : "CONTINUE TO TRANSFORM"} <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// Reusable scrollable table-picker for stages with many tables.
// Replaces the wrap-grid of buttons that becomes unusable past ~30
// tables. Includes a search input and an optional rename mode (used by
// the Transform stage). Each row shows row-count for context.
function RlTableSidebar({
	tables,
	activeTable,
	onPick,
	rename,
	badge,
}: {
	tables: { name: string; rowCount: number }[];
	activeTable: string;
	onPick: (name: string) => void;
	rename?: {
		names: Record<string, string>;
		setNames: (
			updater: (prev: Record<string, string>) => Record<string, string>,
		) => void;
		renaming: string | null;
		setRenaming: (n: string | null) => void;
	};
	badge?: (name: string) => ReactNode;
}) {
	const [search, setSearch] = useState("");
	const filtered = useMemo(() => {
		const q = search.trim().toLowerCase();
		if (!q) return tables;
		return tables.filter((t) => t.name.toLowerCase().includes(q));
	}, [tables, search]);

	return (
		<div
			className="panel"
			style={{
				display: "flex",
				flexDirection: "column",
				maxHeight: "calc(100vh - 220px)",
				minHeight: 320,
			}}
		>
			<div className="panel-head">TABLES · {tables.length}</div>
			<div
				style={{
					padding: "8px 10px",
					borderBottom: "1px solid var(--lg-border)",
					background: "var(--lg-bg-2)",
				}}
			>
				<input
					placeholder="Search tables…"
					value={search}
					onChange={(e) => setSearch(e.target.value)}
					style={{
						width: "100%",
						fontSize: 11,
						padding: "5px 8px",
						background: "var(--lg-bg)",
						border: "1px solid var(--lg-border)",
						color: "var(--lg-ink)",
						fontFamily: "var(--lg-mono)",
						textTransform: "none",
						letterSpacing: 0,
						outline: "none",
					}}
				/>
			</div>
			<div style={{ overflowY: "auto", flex: 1, minHeight: 0 }}>
				{filtered.length === 0 ? (
					<div
						className="mono"
						style={{
							fontSize: 11,
							color: "var(--lg-ink-mute)",
							padding: 14,
							textAlign: "center",
						}}
					>
						No matches.
					</div>
				) : (
					filtered.map((t) => {
						const active = t.name === activeTable;
						const renamed =
							rename && rename.names[t.name] && rename.names[t.name] !== t.name;
						const isRenaming = rename?.renaming === t.name;
						return (
							<div
								key={t.name}
								onClick={() => onPick(t.name)}
								style={{
									display: "flex",
									alignItems: "center",
									gap: 6,
									padding: "6px 10px",
									cursor: "pointer",
									background: active ? "var(--lg-amber)" : "transparent",
									color: active ? "#0a0410" : "var(--lg-ink)",
									borderBottom: "1px solid var(--lg-border)",
									fontFamily: "var(--lg-pixel)",
									fontSize: 9,
									letterSpacing: "0.08em",
								}}
							>
								{isRenaming && rename ? (
									<input
										value={rename.names[t.name] ?? t.name}
										onClick={(e) => e.stopPropagation()}
										onChange={(e) =>
											rename.setNames((prev) => ({
												...prev,
												[t.name]: e.target.value,
											}))
										}
										onKeyDown={(e) => {
											if (e.key === "Enter") rename.setRenaming(null);
											if (e.key === "Escape") {
												rename.setNames((prev) => ({
													...prev,
													[t.name]: t.name,
												}));
												rename.setRenaming(null);
											}
										}}
										onBlur={() => rename.setRenaming(null)}
										autoFocus
										style={{
											flex: 1,
											padding: "2px 6px",
											fontSize: 10,
											background: "var(--lg-bg)",
											border: "1px solid var(--lg-border)",
											color: "var(--lg-ink)",
											fontFamily: "var(--lg-mono)",
											textTransform: "none",
											letterSpacing: 0,
										}}
									/>
								) : (
									<>
										<div
											style={{
												flex: 1,
												overflow: "hidden",
												textOverflow: "ellipsis",
												whiteSpace: "nowrap",
											}}
											title={t.name}
										>
											{renamed ? (
												<>
													<span
														style={{
															opacity: 0.5,
															textDecoration: "line-through",
															marginRight: 4,
														}}
													>
														{t.name.toUpperCase()}
													</span>
													{(rename!.names[t.name] ?? t.name).toUpperCase()}
												</>
											) : (
												t.name.toUpperCase()
											)}
										</div>
										{badge && badge(t.name)}
										<span
											style={{
												fontFamily: "var(--lg-mono)",
												fontSize: 9,
												opacity: 0.7,
												letterSpacing: 0,
											}}
										>
											{t.rowCount.toLocaleString()}
										</span>
										{rename && (
											<button
												className="btn btn-ghost"
												title="Rename"
												onClick={(e) => {
													e.stopPropagation();
													rename.setRenaming(t.name);
												}}
												style={{
													padding: "1px 5px",
													fontSize: 9,
													opacity: 0.7,
												}}
											>
												✎
											</button>
										)}
									</>
								)}
							</div>
						);
					})
				)}
			</div>
		</div>
	);
}

type ColOp = "keep" | "rename" | "cast" | "drop" | "add" | "fk";
type ColTransform = {
	op: string;
	params: Record<string, unknown>;
};

// Value generators for added columns. Lets the user say "fill this new
// column with one UUID per row" / "fill with 1, 2, 3, ..." / etc.,
// instead of a single static defaultValue. The backend Transformer
// reads these and generates per-row when running the pipeline.
type ColGenerator =
	| { kind: "fixed"; value: string }
	| { kind: "uuid_v4" }
	| { kind: "increment"; start?: number; step?: number }
	| { kind: "now" }
	| { kind: "from_column"; source_column: string }
	| { kind: "concat"; template: string }; // template like "{first_name} {last_name}"

type ColEdit = {
	name: string;
	type: string;
	op: ColOp;
	targetName: string;
	targetType: string;
	isNew?: boolean;
	nullable?: boolean;
	defaultValue?: string;
	generator?: ColGenerator;
	fkSourceTable?: string;
	fkSourceColumn?: string;
	fkMatchColumn?: string;
	fkLocalColumn?: string;
	transforms?: ColTransform[];
};

// Table-level filter, mirrors backend models.RowFilter. Conditions are ANDed.
type FilterOp =
	| "eq" | "ne" | "in" | "not_in"
	| "gt" | "lt" | "ge" | "le"
	| "is_null" | "is_not_null"
	| "contains" | "starts_with";
type FilterCondition = { column: string; op: FilterOp; value?: unknown };
type RowFilter = { mode: "keep" | "drop"; conditions: FilterCondition[] };

const CAST_TYPES = [
	"string", "integer", "float", "boolean",
	"text", "varchar", "char",
	"smallint", "bigint", "numeric", "decimal", "real", "double",
	"date", "time", "timestamp", "datetime",
	"uuid", "json", "blob",
];

const TRANSFORM_OPS: { id: string; label: string; params: { key: string; label: string; type: string; placeholder?: string; options?: { value: string; label: string }[] }[] }[] = [
	{ id: "normalize_phone", label: "NORMALIZE PHONE", params: [
		{ key: "country_code", label: "COUNTRY CODE", placeholder: "+970", type: "text" },
		{ key: "strip", label: "STRIP CHARS", placeholder: " -()/.", type: "text" },
	]},
	{ id: "split_name", label: "SPLIT NAME", params: [
		{ key: "part", label: "EXTRACT", type: "select", options: [
			{ value: "first", label: "First word" },
			{ value: "last", label: "Last word" },
			{ value: "all_but_last", label: "All but last" },
			{ value: "all_but_first", label: "All but first" },
		]},
		{ key: "separator", label: "SEPARATOR", placeholder: " ", type: "text" },
		{ key: "default", label: "DEFAULT", placeholder: "(original)", type: "text" },
	]},
	{ id: "map_values", label: "MAP VALUES", params: [
		{ key: "mapping", label: "MAPPING (key=value, one per line)", type: "textarea" },
		{ key: "default", label: "IF NO MATCH", placeholder: "original", type: "text" },
		{ key: "case_insensitive", label: "CASE INSENSITIVE", type: "checkbox" },
	]},
	{ id: "generate_uuid", label: "GENERATE UUID", params: [
		{ key: "deterministic", label: "DETERMINISTIC (same input = same UUID)", type: "checkbox" },
		{ key: "namespace", label: "NAMESPACE", placeholder: "etl-legacy", type: "text" },
		{ key: "keep_original", label: "ONLY FILL NULLS", type: "checkbox" },
	]},
	{ id: "default_if_null", label: "DEFAULT IF NULL", params: [
		{ key: "value", label: "DEFAULT VALUE", placeholder: "N/A", type: "text" },
		{ key: "treat_empty_as_null", label: "TREAT EMPTY AS NULL", type: "checkbox" },
	]},
	{ id: "conditional", label: "CONDITIONAL MAP", params: [
		{ key: "rules", label: "RULES (when=then, one per line)", type: "textarea" },
		{ key: "default", label: "IF NO MATCH", placeholder: "original", type: "text" },
		{ key: "case_insensitive", label: "CASE INSENSITIVE", type: "checkbox" },
	]},
	{ id: "compute", label: "COMPUTE (ARITHMETIC)", params: [
		{ key: "expression", label: "EXPRESSION e.g. {qty} * {price} - {discount}", placeholder: "{value} * 1.17", type: "text" },
		{ key: "round", label: "ROUND TO N DECIMALS (blank = no round)", placeholder: "2", type: "text" },
		{ key: "null_as", label: "NULL TREATED AS", placeholder: "0", type: "text" },
	]},
];

// Mirrors the backend Transformer's per-cell logic so the BEFORE/AFTER
// pane can show what each transform actually does without a server
// roundtrip. Kept in lockstep with backend/core/transformer.py — when
// you add a new transform op there, add it here too.
function applyTransformToValue(
	value: unknown,
	transform: { op: string; params: Record<string, unknown> },
	row: Record<string, unknown>,
): unknown {
	const params = transform.params ?? {};
	const v = value;
	switch (transform.op) {
		case "normalize_phone": {
			if (v == null) return v;
			let s = String(v);
			const stripChars = String(params.strip ?? " -()/.");
			for (const ch of stripChars) s = s.split(ch).join("");
			const cc = String(params.country_code ?? "");
			if (cc && !s.startsWith(cc)) s = cc + s.replace(/^0+/, "");
			return s;
		}
		case "split_name": {
			if (v == null) return v;
			const s = String(v);
			const sep = String(params.separator ?? " ");
			const parts = s.split(sep).filter((p) => p.length > 0);
			const part = String(params.part ?? "first");
			const def = params.default != null ? String(params.default) : s;
			if (parts.length === 0) return def;
			if (part === "first") return parts[0];
			if (part === "last") return parts[parts.length - 1];
			if (part === "all_but_last")
				return parts.length > 1 ? parts.slice(0, -1).join(sep) : def;
			if (part === "all_but_first")
				return parts.length > 1 ? parts.slice(1).join(sep) : def;
			return s;
		}
		case "map_values": {
			if (v == null) return v;
			const mapping = String(params.mapping ?? "");
			const ci = !!params.case_insensitive;
			const lookup: Record<string, string> = {};
			for (const line of mapping.split("\n")) {
				const eq = line.indexOf("=");
				if (eq < 0) continue;
				const k = line.slice(0, eq).trim();
				const val = line.slice(eq + 1).trim();
				if (!k) continue;
				lookup[ci ? k.toLowerCase() : k] = val;
			}
			const key = ci ? String(v).toLowerCase() : String(v);
			if (key in lookup) return lookup[key];
			const def = params.default;
			return def != null && String(def).length > 0 ? String(def) : v;
		}
		case "generate_uuid": {
			const keepOriginal = !!params.keep_original;
			if (keepOriginal && v != null && String(v).length > 0) return v;
			try {
				return typeof crypto !== "undefined" && crypto.randomUUID
					? crypto.randomUUID()
					: "00000000-0000-0000-0000-000000000000";
			} catch {
				return "00000000-0000-0000-0000-000000000000";
			}
		}
		case "default_if_null": {
			const treatEmpty = !!params.treat_empty_as_null;
			const isEmpty = v == null || (treatEmpty && String(v).trim() === "");
			return isEmpty ? String(params.value ?? "") : v;
		}
		case "conditional": {
			if (v == null) return v;
			const rules = String(params.rules ?? "");
			const ci = !!params.case_insensitive;
			const key = ci ? String(v).toLowerCase() : String(v);
			for (const line of rules.split("\n")) {
				const eq = line.indexOf("=");
				if (eq < 0) continue;
				const cond = line.slice(0, eq).trim();
				const result = line.slice(eq + 1).trim();
				if ((ci ? cond.toLowerCase() : cond) === key) return result;
			}
			const def = params.default;
			return def != null && String(def).length > 0 ? String(def) : v;
		}
		case "compute": {
			// Tiny arithmetic evaluator mirroring backend `compute` op so
			// the BEFORE/AFTER preview shows a useful value. Whitelisted
			// to + - * / % parens and {col} placeholders that resolve to
			// the current row.
			const expr = String(params.expression ?? "");
			if (!expr) return v;
			const nullAs = Number(params.null_as ?? 0) || 0;
			const decimalsRaw = String(params.round ?? "").trim();
			const decimals = decimalsRaw === "" ? null : Number(decimalsRaw);

			const substituted = expr.replace(/\{([^{}]+)\}/g, (_m, key) => {
				const raw = key === "value" ? v : (row as Record<string, unknown>)[key];
				if (raw == null || raw === "") return String(nullAs);
				const n = Number(raw);
				return Number.isFinite(n) ? String(n) : String(nullAs);
			});
			// Allow only digits, whitespace, and the operator/paren set.
			if (!/^[\d\s+\-*/%().]*$/.test(substituted)) return null;
			try {
				// eslint-disable-next-line no-new-func
				const result = Function(`"use strict"; return (${substituted});`)();
				if (typeof result !== "number" || !Number.isFinite(result)) return null;
				if (decimals !== null && Number.isFinite(decimals)) {
					return Number(result.toFixed(decimals));
				}
				return Number.isInteger(result) ? Math.trunc(result) : result;
			} catch {
				return null;
			}
		}
	}
	return v;
}

function applyAllTransforms(
	value: unknown,
	col: ColEdit,
	row: Record<string, unknown>,
): unknown {
	let out = value;
	for (const t of col.transforms ?? []) {
		out = applyTransformToValue(out, t, row);
	}
	return out;
}

// Compute the displayed value for an added column. If a generator is
// configured (item 4), simulate it for the row index. Falls back to the
// old `defaultValue` / NULL behavior.
function renderAddedCellPreview(col: ColEdit, rowIndex: number): string | null {
	const gen = col.generator;
	if (gen) {
		switch (gen.kind) {
			case "fixed":
				return gen.value != null && gen.value !== ""
					? gen.value
					: col.nullable
						? null
						: "—";
			case "uuid_v4":
				try {
					return typeof crypto !== "undefined" && crypto.randomUUID
						? crypto.randomUUID()
						: "00000000-0000-0000-0000-000000000000";
				} catch {
					return "00000000-0000-0000-0000-000000000000";
				}
			case "increment": {
				const start = Number(gen.start ?? 1);
				const step = Number(gen.step ?? 1);
				return String(start + rowIndex * step);
			}
			case "now":
				return new Date().toISOString().slice(0, 19) + "Z";
			case "from_column":
				return gen.source_column ?? "(no source column)";
			case "concat": {
				const tpl = String(gen.template ?? "");
				if (!tpl) return col.nullable ? null : "";
				return tpl;
			}
		}
	}
	if (col.nullable) return null;
	return col.defaultValue && col.defaultValue.length > 0 ? col.defaultValue : "—";
}

// Build a one-line human-readable summary of a transform for the
// compact card view. Mirrors the param keys defined in TRANSFORM_OPS so
// each op gets a useful preview without showing the entire form.
function summarizeTransform(t: ColTransform): string {
	const p = t.params ?? {};
	switch (t.op) {
		case "normalize_phone": {
			const cc = String(p.country_code ?? "").trim();
			const strip = String(p.strip ?? "").trim();
			const parts: string[] = [];
			if (cc) parts.push(`cc=${cc}`);
			if (strip) parts.push(`strip="${strip}"`);
			return parts.join(" · ") || "default";
		}
		case "split_name": {
			const part = String(p.part ?? "first");
			const sep = String(p.separator ?? " ");
			return `→ ${part}${sep !== " " ? `, sep="${sep}"` : ""}`;
		}
		case "map_values": {
			const lines = String(p.mapping ?? "")
				.split("\n")
				.filter((l) => l.includes("="));
			const ci = p.case_insensitive ? " (ci)" : "";
			return `${lines.length} mapping${lines.length === 1 ? "" : "s"}${ci}`;
		}
		case "generate_uuid": {
			const det = p.deterministic ? "deterministic" : "random";
			const fill = p.keep_original ? " · only fills nulls" : "";
			return `${det}${fill}`;
		}
		case "default_if_null": {
			const v = String(p.value ?? "");
			const empty = p.treat_empty_as_null ? " (treat empty as null)" : "";
			return v ? `→ "${v}"${empty}` : `→ ""${empty}`;
		}
		case "conditional": {
			const lines = String(p.rules ?? "")
				.split("\n")
				.filter((l) => l.includes("="));
			const ci = p.case_insensitive ? " (ci)" : "";
			return `${lines.length} rule${lines.length === 1 ? "" : "s"}${ci}`;
		}
		case "compute": {
			const expr = String(p.expression ?? "").trim();
			const r = String(p.round ?? "").trim();
			return expr ? `${expr}${r ? ` · round ${r}` : ""}` : "(no expression)";
		}
	}
	return "";
}

// Modal for picking a transform op and configuring its params. Used for
// both adding a new transform and editing an existing one (initial !=
// undefined). Click outside / Esc cancels; Save commits via onSave.
function TransformModal({
	initial,
	onSave,
	onCancel,
}: {
	initial?: ColTransform;
	onSave: (op: string, params: Record<string, unknown>) => void;
	onCancel: () => void;
}) {
	const [op, setOp] = useState<string>(initial?.op ?? TRANSFORM_OPS[0].id);
	const [params, setParams] = useState<Record<string, unknown>>(
		() => ({ ...(initial?.params ?? {}) }),
	);
	const bodyRef = useRef<HTMLDivElement | null>(null);

	// When the user picks a different op, drop params that don't apply
	// (avoids accidentally sending stale params from another op).
	const setOpAndResetParams = (newOp: string) => {
		const meta = TRANSFORM_OPS.find((o) => o.id === newOp);
		const validKeys = new Set((meta?.params ?? []).map((p) => p.key));
		setParams((prev) => {
			const next: Record<string, unknown> = {};
			for (const k of Object.keys(prev)) if (validKeys.has(k)) next[k] = prev[k];
			return next;
		});
		setOp(newOp);
	};

	const opMeta = TRANSFORM_OPS.find((o) => o.id === op);

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			const target = e.target as HTMLElement;
			const tag = target.tagName;
			const isInput = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";

			if (e.key === "Escape") {
				e.preventDefault();
				e.stopPropagation();
				if (isInput) {
					target.blur();
				} else {
					onCancel();
				}
				return;
			}

			// When typing into a field, let it handle its own keys
			if (isInput) return;

			const currentIdx = TRANSFORM_OPS.findIndex((o) => o.id === op);
			let handled = true;

			switch (e.key) {
				case "ArrowUp":
					if (currentIdx > 0) setOpAndResetParams(TRANSFORM_OPS[currentIdx - 1].id);
					break;
				case "ArrowDown":
					if (currentIdx < TRANSFORM_OPS.length - 1)
						setOpAndResetParams(TRANSFORM_OPS[currentIdx + 1].id);
					break;
				case "Enter":
					onSave(op, params);
					break;
				case "x":
				case "X":
					onCancel();
					break;
				case "e":
				case "E": {
					const firstField =
						bodyRef.current?.querySelectorAll<HTMLElement>(
							"input, textarea, select",
						)[1] ?? // skip the op selector itself (index 0)
						bodyRef.current?.querySelector<HTMLElement>(
							"input, textarea, select",
						);
					firstField?.focus();
					if (firstField instanceof HTMLInputElement) firstField.select();
					break;
				}
				default:
					handled = false;
			}

			if (handled) {
				e.preventDefault();
				e.stopPropagation();
			}
		};
		// Capture phase + stopPropagation prevents the parent (e.g.
		// RlTransform's window listener) from also handling these keys.
		document.addEventListener("keydown", onKey, true);
		return () => document.removeEventListener("keydown", onKey, true);
	}, [op, params, onCancel, onSave]);

	return createPortal(
		<div
			style={{
				position: "fixed",
				inset: 0,
				zIndex: 9999,
				background: "rgba(0,0,0,0.78)",
				display: "grid",
				placeItems: "center",
				padding: 24,
			}}
			onClick={onCancel}
		>
			<div
				onClick={(e) => e.stopPropagation()}
				style={{
					background: "var(--lg-bg)",
					border: "2px solid var(--lg-amber)",
					boxShadow: "0 12px 40px rgba(0,0,0,0.65)",
					width: "min(560px, 92vw)",
					maxHeight: "85vh",
					display: "flex",
					flexDirection: "column",
					overflow: "hidden",
					color: "var(--lg-ink)",
				}}
			>
				{/* Header */}
				<div
					style={{
						display: "flex",
						alignItems: "center",
						justifyContent: "space-between",
						padding: "10px 14px",
						borderBottom: "1px solid var(--lg-border)",
						background: "var(--lg-bg-2)",
					}}
				>
					<span
						className="pixel"
						style={{
							fontSize: 11,
							color: "var(--lg-amber)",
							letterSpacing: "0.1em",
						}}
					>
						{initial ? "EDIT TRANSFORM" : "ADD TRANSFORM"}
					</span>
					<button
						className="link"
						onClick={onCancel}
						style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}
					>
						<IX size={10} /> CLOSE
					</button>
				</div>

				{/* Body */}
				<div
					ref={bodyRef}
					style={{
						padding: "16px 14px",
						overflowY: "auto",
						display: "flex",
						flexDirection: "column",
						gap: 12,
					}}
				>
					<div>
						<div
							className="pixel"
							style={{
								fontSize: 10,
								color: "var(--lg-ink-mute)",
								letterSpacing: "0.1em",
								marginBottom: 4,
								display: "flex",
								justifyContent: "space-between",
							}}
						>
							<span>TRANSFORM</span>
							<span style={{ color: "var(--lg-ink-faint)" }}>
								{TRANSFORM_OPS.findIndex((o) => o.id === op) + 1}/{TRANSFORM_OPS.length}
							</span>
						</div>
						<select
							className="input"
							value={op}
							onChange={(e) => setOpAndResetParams(e.target.value)}
						>
							{TRANSFORM_OPS.map((o) => (
								<option key={o.id} value={o.id}>
									{o.label}
								</option>
							))}
						</select>
					</div>

					{(opMeta?.params ?? []).map((p) => (
						<div key={p.key}>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-ink-mute)",
									letterSpacing: "0.1em",
									marginBottom: 4,
								}}
							>
								{p.label}
							</div>
							{p.type === "text" && (
								<input
									className="input"
									placeholder={p.placeholder ?? ""}
									value={String(params[p.key] ?? "")}
									onChange={(e) =>
										setParams((prev) => ({ ...prev, [p.key]: e.target.value }))
									}
								/>
							)}
							{p.type === "select" && (
								<select
									className="input"
									value={String(params[p.key] ?? "")}
									onChange={(e) =>
										setParams((prev) => ({ ...prev, [p.key]: e.target.value }))
									}
								>
									<option value="">—</option>
									{p.options?.map((o) => (
										<option key={o.value} value={o.value}>
											{o.label}
										</option>
									))}
								</select>
							)}
							{p.type === "checkbox" && (
								<label
									style={{
										display: "flex",
										alignItems: "center",
										gap: 8,
										fontSize: 11,
										cursor: "pointer",
									}}
								>
									<input
										type="checkbox"
										checked={!!params[p.key]}
										onChange={(e) =>
											setParams((prev) => ({
												...prev,
												[p.key]: e.target.checked,
											}))
										}
									/>
									<span className="mono" style={{ color: "var(--lg-ink-dim)" }}>
										enabled
									</span>
								</label>
							)}
							{p.type === "textarea" && (
								<textarea
									className="input"
									style={{
										minHeight: 90,
										resize: "vertical",
										fontFamily: "var(--lg-mono)",
										fontSize: 11,
									}}
									placeholder={
										p.key === "mapping"
											? "ILS=NIS\nUSD=USD"
											: p.key === "rules"
												? "posted=delivered\ndraft=draft"
												: ""
									}
									value={String(params[p.key] ?? "")}
									onChange={(e) =>
										setParams((prev) => ({ ...prev, [p.key]: e.target.value }))
									}
								/>
							)}
						</div>
					))}
				</div>

				{/* Footer */}
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						alignItems: "center",
						gap: 8,
						padding: "10px 14px",
						borderTop: "1px solid var(--lg-border)",
						background: "var(--lg-bg-2)",
					}}
				>
					<div
						className="mono"
						style={{ fontSize: 9, color: "var(--lg-ink-faint)" }}
					>
						<span style={{ color: "var(--lg-amber)" }}>↑↓</span> NAV ·{" "}
						<span style={{ color: "var(--lg-amber)" }}>E</span> EDIT ·{" "}
						<span style={{ color: "var(--lg-amber)" }}>↵</span> {initial ? "UPDATE" : "ADD"} ·{" "}
						<span style={{ color: "var(--lg-amber)" }}>X</span>/<span style={{ color: "var(--lg-amber)" }}>ESC</span> CLOSE
					</div>
					<div style={{ display: "flex", gap: 8 }}>
						<button
							className="btn btn-ghost"
							style={{ padding: "6px 14px", fontSize: 10 }}
							onClick={onCancel}
						>
							CANCEL
						</button>
						<button
							className="btn btn-primary"
							style={{ padding: "6px 14px", fontSize: 10 }}
							onClick={() => onSave(op, params)}
						>
							{initial ? "UPDATE" : "ADD"}
						</button>
					</div>
				</div>
			</div>
		</div>,
		document.body,
	);
}

// Compact, scrollable list of transform "cards" with an Add button.
// Each card is clickable to edit (re-opens TransformModal).
function TransformsCardList({
	transforms,
	onAdd,
	onReplace,
	onRemove,
}: {
	transforms: ColTransform[];
	onAdd: (op: string, params: Record<string, unknown>) => void;
	onReplace: (idx: number, op: string, params: Record<string, unknown>) => void;
	onRemove: (idx: number) => void;
}) {
	const [adding, setAdding] = useState(false);
	const [editingIdx, setEditingIdx] = useState<number | null>(null);
	const editingTransform =
		editingIdx !== null ? transforms[editingIdx] : undefined;

	// Shortcut: press T to open the Add Transform modal directly
	useEffect(() => {
		const handler = (e: KeyboardEvent) => {
			const target = e.target as HTMLElement;
			const tag = target.tagName;
			if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
			if (adding || editingIdx !== null) return;
			if (e.key === "t" || e.key === "T") {
				e.preventDefault();
				setAdding(true);
			}
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, [adding, editingIdx]);

	return (
		<div
			style={{
				marginTop: 16,
				borderTop: "1px solid var(--lg-border)",
				paddingTop: 12,
			}}
		>
			<div
				style={{
					display: "flex",
					justifyContent: "space-between",
					alignItems: "center",
					marginBottom: 8,
				}}
			>
				<div
					className="pixel"
					style={{
						fontSize: 10,
						color: "var(--lg-ink-mute)",
						letterSpacing: "0.1em",
					}}
				>
					TRANSFORMS{transforms.length ? ` (${transforms.length})` : ""}
				</div>
				<button
					className="btn btn-ghost"
					style={{ padding: "3px 8px", fontSize: 9 }}
					onClick={() => setAdding(true)}
					title="Press T"
				>
					+ ADD <span style={{ color: "var(--lg-amber)", marginLeft: 4 }}>[T]</span>
				</button>
			</div>

			<div
				style={{
					maxHeight: 220,
					overflowY: "auto",
					display: "flex",
					flexDirection: "column",
					gap: 4,
					paddingRight: 2,
				}}
			>
				{transforms.length === 0 ? (
					<div
						className="mono"
						style={{
							fontSize: 10,
							color: "var(--lg-ink-mute)",
							padding: "8px 4px",
						}}
					>
						No transforms yet — click + ADD to chain one.
					</div>
				) : (
					transforms.map((t, idx) => {
						const opMeta = TRANSFORM_OPS.find((o) => o.id === t.op);
						return (
							<div
								key={idx}
								onClick={() => setEditingIdx(idx)}
								style={{
									cursor: "pointer",
									padding: "6px 8px",
									border: "1px solid var(--lg-border)",
									background: "var(--lg-bg-2)",
									display: "flex",
									alignItems: "center",
									gap: 6,
									minWidth: 0,
								}}
								title="Click to edit"
							>
								<span
									className="pixel"
									style={{
										fontSize: 8,
										color: "var(--lg-ink-mute)",
										width: 16,
									}}
								>
									{idx + 1}.
								</span>
								<div style={{ flex: 1, minWidth: 0 }}>
									<div
										className="pixel"
										style={{
											fontSize: 9,
											color: "var(--lg-amber)",
											letterSpacing: "0.08em",
											overflow: "hidden",
											textOverflow: "ellipsis",
											whiteSpace: "nowrap",
										}}
									>
										{opMeta?.label ?? t.op.toUpperCase()}
									</div>
									<div
										className="mono"
										style={{
											fontSize: 9,
											color: "var(--lg-ink-dim)",
											overflow: "hidden",
											textOverflow: "ellipsis",
											whiteSpace: "nowrap",
										}}
									>
										{summarizeTransform(t) || " "}
									</div>
								</div>
								<button
									className="link"
									style={{ fontSize: 9, color: "var(--lg-coral)" }}
									onClick={(e) => {
										e.stopPropagation();
										onRemove(idx);
									}}
									title="Remove"
								>
									<IX size={8} />
								</button>
							</div>
						);
					})
				)}
			</div>

			{(adding || editingIdx !== null) && (
				<TransformModal
					initial={editingTransform}
					onSave={(op, params) => {
						if (editingIdx !== null) onReplace(editingIdx, op, params);
						else onAdd(op, params);
						setAdding(false);
						setEditingIdx(null);
					}}
					onCancel={() => {
						setAdding(false);
						setEditingIdx(null);
					}}
				/>
			)}
		</div>
	);
}

// Editor widget for added-column value generators.
// Shows a "kind" dropdown plus the params relevant to the picked kind.
function GeneratorEditor({
	col,
	otherColumns,
	onChange,
}: {
	col: ColEdit;
	otherColumns: string[];
	onChange: (gen: ColGenerator | undefined) => void;
}) {
	// Treat "no generator yet, but has defaultValue" as fixed-with-that-value
	// so existing presets / older state files keep working when the user
	// switches in. New columns default to fixed/empty.
	const current: ColGenerator =
		col.generator ??
		(col.defaultValue !== undefined
			? { kind: "fixed", value: col.defaultValue ?? "" }
			: { kind: "fixed", value: "" });

	const setKind = (kind: ColGenerator["kind"]) => {
		switch (kind) {
			case "fixed":
				onChange({ kind: "fixed", value: "" });
				return;
			case "uuid_v4":
				onChange({ kind: "uuid_v4" });
				return;
			case "increment":
				onChange({ kind: "increment", start: 1, step: 1 });
				return;
			case "now":
				onChange({ kind: "now" });
				return;
			case "from_column":
				onChange({ kind: "from_column", source_column: otherColumns[0] ?? "" });
				return;
			case "concat":
				onChange({ kind: "concat", template: "" });
				return;
		}
	};

	const inputStyle: React.CSSProperties = {
		fontSize: 10,
		padding: "3px 6px",
		fontFamily: "var(--lg-mono)",
		textTransform: "none",
		letterSpacing: 0,
	};

	return (
		<>
			<div
				className="pixel"
				style={{
					fontSize: 10,
					color: "var(--lg-ink-mute)",
					marginBottom: 4,
					letterSpacing: "0.1em",
				}}
			>
				FILL WITH
			</div>
			<select
				className="input"
				style={{ marginBottom: 8 }}
				value={current.kind}
				onChange={(e) => setKind(e.target.value as ColGenerator["kind"])}
			>
				<option value="fixed">Fixed value (same for all rows)</option>
				<option value="uuid_v4">UUID v4 (random per row)</option>
				<option value="increment">Increment (1, 2, 3…)</option>
				<option value="now">Now (current timestamp)</option>
				<option value="from_column">Copy another column</option>
				<option value="concat">Template (concat columns + literals)</option>
			</select>

			{current.kind === "fixed" && (
				<input
					className="input"
					placeholder="value used for every row"
					value={current.value}
					onChange={(e) => onChange({ kind: "fixed", value: e.target.value })}
				/>
			)}

			{current.kind === "uuid_v4" && (
				<div
					style={{
						padding: 8,
						border: "1px solid var(--lg-border)",
						color: "var(--lg-ink-dim)",
						fontSize: 10,
						lineHeight: 1.5,
					}}
				>
					Each row gets a fresh random UUID v4 (e.g.{" "}
					<span className="mono" style={{ color: "var(--lg-amber)" }}>
						3f2504e0-4f89-41d3-9a0c-0305e82c3301
					</span>
					).
				</div>
			)}

			{current.kind === "increment" && (
				<div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
					<div>
						<div
							className="pixel"
							style={{
								fontSize: 8,
								color: "var(--lg-ink-mute)",
								marginBottom: 2,
								letterSpacing: "0.08em",
							}}
						>
							START
						</div>
						<input
							className="input"
							type="number"
							style={inputStyle}
							value={current.start ?? 1}
							onChange={(e) =>
								onChange({
									kind: "increment",
									start: Number(e.target.value),
									step: current.step ?? 1,
								})
							}
						/>
					</div>
					<div>
						<div
							className="pixel"
							style={{
								fontSize: 8,
								color: "var(--lg-ink-mute)",
								marginBottom: 2,
								letterSpacing: "0.08em",
							}}
						>
							STEP
						</div>
						<input
							className="input"
							type="number"
							style={inputStyle}
							value={current.step ?? 1}
							onChange={(e) =>
								onChange({
									kind: "increment",
									start: current.start ?? 1,
									step: Number(e.target.value),
								})
							}
						/>
					</div>
				</div>
			)}

			{current.kind === "now" && (
				<div
					style={{
						padding: 8,
						border: "1px solid var(--lg-border)",
						color: "var(--lg-ink-dim)",
						fontSize: 10,
					}}
				>
					Each row gets the timestamp the transform was run (UTC ISO-8601).
				</div>
			)}

			{current.kind === "from_column" && (
				<select
					className="input"
					style={inputStyle}
					value={current.source_column}
					onChange={(e) =>
						onChange({ kind: "from_column", source_column: e.target.value })
					}
				>
					<option value="">— pick a column —</option>
					{otherColumns.map((c2) => (
						<option key={c2} value={c2}>
							{c2}
						</option>
					))}
				</select>
			)}

			{current.kind === "concat" && (
				<>
					<input
						className="input"
						style={inputStyle}
						placeholder="e.g. {first_name} {last_name}"
						value={current.template}
						onChange={(e) =>
							onChange({ kind: "concat", template: e.target.value })
						}
					/>
					<div
						className="mono"
						style={{
							fontSize: 9,
							color: "var(--lg-ink-mute)",
							marginTop: 4,
							lineHeight: 1.5,
						}}
					>
						Use {"{column_name}"} placeholders. Other text is literal.
					</div>
				</>
			)}
		</>
	);
}

function resolveType(colInfo: unknown): string {
	if (typeof colInfo === "object" && colInfo) {
		const ci = colInfo as Record<string, unknown>;
		return String(ci.inferred_type ?? ci.original_type ?? "string");
	}
	return String(colInfo ?? "string");
}

type TransformPresetSummary = {
	id: string;
	name: string;
	schema_signature: string[];
	table_count: number;
	created_at: string;
	updated_at: string;
};

type TransformPreset = TransformPresetSummary & {
	table_names: Record<string, string>;
	edits: Record<string, ColEdit[]>;
	// Optional new fields, used by the AL-ARABI preset and any successor:
	// `dropped_tables` — sources to skip in the transformer.
	// `table_options[t].row_filter` — keep/drop predicate per table.
	// `extra_configs` — additional outputs from one source so the user can
	// build UNIONed tables like product_barcodes.
	dropped_tables?: string[];
	table_options?: Record<string, { row_filter?: RowFilter }>;
	extra_configs?: Array<{ source: string; target: string; edits: ColEdit[] }>;
};

async function listTransformPresets(): Promise<TransformPresetSummary[]> {
	try {
		const res = await fetch("/api/transform-presets");
		if (!res.ok) return [];
		const data = (await res.json()) as { presets: TransformPresetSummary[] };
		return data.presets ?? [];
	} catch {
		return [];
	}
}

async function getTransformPreset(id: string): Promise<TransformPreset | null> {
	try {
		const res = await fetch(`/api/transform-presets/${id}`);
		if (!res.ok) return null;
		return (await res.json()) as TransformPreset;
	} catch {
		return null;
	}
}

async function createTransformPreset(
	name: string,
	tableNames: Record<string, string>,
	edits: Record<string, ColEdit[]>,
): Promise<TransformPreset | null> {
	try {
		const res = await fetch("/api/transform-presets", {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ name, table_names: tableNames, edits }),
		});
		if (!res.ok) return null;
		return (await res.json()) as TransformPreset;
	} catch {
		return null;
	}
}

async function updateTransformPreset(
	id: string,
	tableNames: Record<string, string>,
	edits: Record<string, ColEdit[]>,
): Promise<TransformPreset | null> {
	try {
		const res = await fetch(`/api/transform-presets/${id}`, {
			method: "PUT",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ table_names: tableNames, edits }),
		});
		if (!res.ok) return null;
		return (await res.json()) as TransformPreset;
	} catch {
		return null;
	}
}

async function deleteTransformPreset(id: string): Promise<boolean> {
	try {
		const res = await fetch(`/api/transform-presets/${id}`, {
			method: "DELETE",
		});
		return res.ok;
	} catch {
		return false;
	}
}

// Compact panel of table-level actions: drop the entire table, or filter
// rows by a small AND-of-conditions predicate. Sits above the per-column
// edit area in the Transform stage.
function TableActionsPanel({
	tableName,
	isDropped,
	setDropped,
	rowFilter,
	setRowFilter,
	availableColumns,
	extraOutputs,
}: {
	tableName: string;
	isDropped: boolean;
	setDropped: (dropped: boolean) => void;
	rowFilter: RowFilter | undefined;
	setRowFilter: (rf: RowFilter | undefined) => void;
	availableColumns: string[];
	extraOutputs: string[];
}) {
	const conditions = rowFilter?.conditions ?? [];
	const mode: "keep" | "drop" = rowFilter?.mode ?? "keep";

	const updateFilter = (next: RowFilter | undefined) => {
		if (next && next.conditions.length === 0) {
			setRowFilter(undefined);
			return;
		}
		setRowFilter(next);
	};

	const addCondition = () => {
		const col = availableColumns[0] ?? "";
		const next: RowFilter = {
			mode,
			conditions: [...conditions, { column: col, op: "eq", value: "" }],
		};
		updateFilter(next);
	};

	const updateCondition = (i: number, patch: Partial<FilterCondition>) => {
		const nextConds = conditions.map((c, idx) =>
			idx === i ? { ...c, ...patch } : c,
		);
		updateFilter({ mode, conditions: nextConds });
	};

	const removeCondition = (i: number) => {
		const nextConds = conditions.filter((_, idx) => idx !== i);
		updateFilter(nextConds.length === 0 ? undefined : { mode, conditions: nextConds });
	};

	const FILTER_OPS: { id: FilterOp; label: string; needsValue: boolean }[] = [
		{ id: "eq", label: "=", needsValue: true },
		{ id: "ne", label: "≠", needsValue: true },
		{ id: "gt", label: ">", needsValue: true },
		{ id: "lt", label: "<", needsValue: true },
		{ id: "ge", label: "≥", needsValue: true },
		{ id: "le", label: "≤", needsValue: true },
		{ id: "contains", label: "contains", needsValue: true },
		{ id: "starts_with", label: "starts with", needsValue: true },
		{ id: "is_null", label: "is null", needsValue: false },
		{ id: "is_not_null", label: "is not null", needsValue: false },
	];

	return (
		<div
			className="panel"
			style={{
				borderColor: isDropped ? "var(--lg-rose)" : undefined,
			}}
		>
			<div
				className="panel-head"
				style={{ display: "flex", alignItems: "center", gap: 8 }}
			>
				<span>TABLE ACTIONS</span>
				<span
					className="mono"
					style={{
						fontSize: 9,
						color: "var(--lg-ink-mute)",
						letterSpacing: 0,
						textTransform: "none",
						fontWeight: "normal",
					}}
				>
					(applied to <b>{tableName}</b> as a whole)
				</span>
			</div>
			<div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
				{/* DROP TABLE */}
				<label
					style={{
						display: "flex",
						alignItems: "center",
						gap: 8,
						cursor: "pointer",
					}}
				>
					<input
						type="checkbox"
						checked={isDropped}
						onChange={(e) => setDropped(e.target.checked)}
					/>
					<span className="pixel" style={{ fontSize: 9, letterSpacing: "0.1em" }}>
						DROP TABLE
					</span>
					<span className="mono" style={{ fontSize: 9, color: "var(--lg-ink-mute)" }}>
						exclude this table from the transformed output entirely
					</span>
				</label>

				{/* ROW FILTER */}
				{!isDropped && (
					<div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
						<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
							<span className="pixel" style={{ fontSize: 9, letterSpacing: "0.1em" }}>
								ROW FILTER
							</span>
							<select
								value={mode}
								onChange={(e) =>
									updateFilter({
										mode: e.target.value as "keep" | "drop",
										conditions,
									})
								}
								style={{ fontSize: 10 }}
								disabled={conditions.length === 0}
							>
								<option value="keep">keep rows where ALL of …</option>
								<option value="drop">drop rows where ALL of …</option>
							</select>
							<button
								type="button"
								className="btn-pixel"
								style={{ fontSize: 9, padding: "2px 6px" }}
								onClick={addCondition}
								disabled={availableColumns.length === 0}
							>
								+ ADD CONDITION
							</button>
						</div>
						{conditions.map((c, i) => {
							const opSpec = FILTER_OPS.find((o) => o.id === c.op);
							return (
								<div
									key={i}
									style={{
										display: "flex",
										alignItems: "center",
										gap: 6,
										paddingLeft: 10,
									}}
								>
									<select
										value={c.column}
										onChange={(e) => updateCondition(i, { column: e.target.value })}
										style={{ fontSize: 10 }}
									>
										{availableColumns.map((col) => (
											<option key={col} value={col}>
												{col}
											</option>
										))}
									</select>
									<select
										value={c.op}
										onChange={(e) =>
											updateCondition(i, { op: e.target.value as FilterOp })
										}
										style={{ fontSize: 10 }}
									>
										{FILTER_OPS.map((o) => (
											<option key={o.id} value={o.id}>
												{o.label}
											</option>
										))}
									</select>
									{opSpec?.needsValue && (
										<input
											type="text"
											className="input-pixel"
											style={{ fontSize: 10, width: 140 }}
											placeholder="value"
											value={(c.value as string) ?? ""}
											onChange={(e) => updateCondition(i, { value: e.target.value })}
										/>
									)}
									<button
										type="button"
										className="btn-pixel"
										style={{ fontSize: 9, padding: "2px 6px" }}
										onClick={() => removeCondition(i)}
										title="Remove condition"
									>
										×
									</button>
								</div>
							);
						})}
					</div>
				)}

				{/* EXTRA OUTPUTS info — populated by presets like AL-ARABI */}
				{extraOutputs.length > 0 && (
					<div
						className="mono"
						style={{
							fontSize: 9,
							color: "var(--lg-ink-mute)",
							borderTop: "1px dashed var(--lg-ink-mute)",
							paddingTop: 6,
						}}
					>
						<b>UNION outputs:</b> this source also feeds {extraOutputs.join(", ")} (configured by the active preset).
					</div>
				)}
			</div>
		</div>
	);
}

function RlTransform({ onNext }: { onNext: () => void }) {
	const { uploadResult, transformResult, setTransformResult, projectId } =
		usePipelineCtx();
	const [strategies, setStrategies] = useState<TransformPresetSummary[]>([]);
	const [sel, setSel] = useState<string>("");
	const [running, setRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [result, setResult] = useState<TransformResult | null>(
		transformResult ?? null,
	);

	const excluded = useMemo(
		() => new Set(uploadResult?.excludedTables ?? []),
		[uploadResult?.excludedTables],
	);
	const tables = (uploadResult?.tables ?? []).filter(
		(t) => !excluded.has(t.name),
	);
	const schema = uploadResult?.schema ?? {};

	useEffect(() => {
		void listTransformPresets().then(setStrategies);
	}, []);

	// Strategy metadata — color/tier/tag/desc, heuristic mapping by name.
	// Strategies that don't match a known shape fall back to "PARTNER / B".
	const meta = (s: TransformPresetSummary) => {
		const n = s.name.toLowerCase();
		if (n.includes("erpnext")) {
			return {
				color: "var(--lg-magenta)",
				tier: "S",
				tag: "OFFICIAL",
				desc: "Standard ERPNext doctype layout. Customers, items, invoices, ledgers.",
			};
		}
		if (n.includes("alarabi") || n.includes("al-arabi")) {
			return {
				color: "var(--lg-cyan)",
				tier: "A",
				tag: "PARTNER",
				desc: "AlArabi internal schema. RTL-safe text, region codes, dual-date.",
			};
		}
		return {
			color: "var(--lg-ink-mute)",
			tier: "B",
			tag: "CUSTOM",
			desc: "Saved transform configuration.",
		};
	};

	// Built-in passthrough: send every table unchanged. Always available so
	// the user has at least one option even with no JSON presets on disk.
	const PASSTHROUGH_ID = "__passthrough__";
	const PASSTHROUGH = {
		id: PASSTHROUGH_ID,
		name: "PASSTHROUGH",
		schema_signature: [],
		table_count: tables.length,
		created_at: "",
		updated_at: "",
	} as TransformPresetSummary;

	const items = [PASSTHROUGH, ...strategies];
	const selectedSummary = items.find((s) => s.id === sel) ?? null;

	const buildConfigFromPreset = (preset: TransformPreset) => {
		// Convert preset.edits into the shape POST /api/configure expects.
		// Only edits present on visible tables are honored; everything else
		// passes through under its source name.
		const tableConfigs = tables.map((t) => {
			const edits = preset.edits[t.name];
			if (!edits) {
				return {
					source_table: t.name,
					target_table: preset.table_names?.[t.name] ?? t.name,
					columns: Object.keys(schema[t.name] ?? {}).map((col) => ({
						name: col,
						target_name: col,
						data_type: resolveType((schema[t.name] ?? {})[col]),
						nullable: true,
						include: true,
					})),
				};
			}
			return {
				source_table: t.name,
				target_table: preset.table_names?.[t.name] ?? t.name,
				columns: edits.map((e) => ({
					name: e.name,
					target_name: e.targetName ?? e.name,
					data_type: e.targetType ?? e.type,
					nullable: e.nullable ?? true,
					include: e.op !== "drop",
					is_new: e.op === "add" || e.op === "fk" || undefined,
					generator: e.generator,
					fk_source_table: e.fkSourceTable,
					fk_source_column: e.fkSourceColumn,
					fk_match_column: e.fkMatchColumn,
					fk_local_column: e.fkLocalColumn,
				})),
				drop_table: preset.dropped_tables?.includes(t.name) || undefined,
				row_filter: preset.table_options?.[t.name]?.row_filter,
			};
		});
		return tableConfigs;
	};

	const buildPassthroughConfig = () =>
		tables.map((t) => ({
			source_table: t.name,
			target_table: t.name,
			columns: Object.keys(schema[t.name] ?? {}).map((col) => ({
				name: col,
				target_name: col,
				data_type: resolveType((schema[t.name] ?? {})[col]),
				nullable: true,
				include: true,
			})),
		}));

	const runTransform = async () => {
		if (!uploadResult?.sessionId) return;
		if (!sel) {
			setError("Pick a strategy first");
			return;
		}
		setRunning(true);
		setError(null);
		try {
			const tableConfigs =
				sel === PASSTHROUGH_ID
					? buildPassthroughConfig()
					: buildConfigFromPreset(
							(await getTransformPreset(sel)) ?? ({} as TransformPreset),
					  );
			const cfgRes = await fetch(
				`/api/configure/${uploadResult.sessionId}`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ tables: tableConfigs }),
				},
			);
			if (!cfgRes.ok) {
				const err = await cfgRes.json().catch(() => null);
				throw new Error(err?.detail || "Configuration failed");
			}
			const lsKey = ACTIVE_TRANSFORM_LS_PREFIX + (projectId ?? "guest");
			try {
				localStorage.setItem(
					lsKey,
					JSON.stringify({
						sessionId: uploadResult.sessionId,
						projectId,
					}),
				);
			} catch {}
			try {
				const res = await fetch(`/api/transform/${uploadResult.sessionId}`);
				if (!res.ok) {
					const err = await res.json().catch(() => null);
					throw new Error(err?.detail || "Transform failed");
				}
				const data = await res.json();
				setResult(data);
				setTransformResult(data);
			} finally {
				try {
					localStorage.removeItem(lsKey);
				} catch {}
			}
		} catch (e) {
			setError(e instanceof Error ? e.message : "Transform failed");
		} finally {
			setRunning(false);
		}
	};

	if (result) {
		return (
			<div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">▼ TRANSFORM COMPLETE</div>
					<div className="panel-body">
						<div className="pixel glow-magenta" style={{ fontSize: 22, color: "var(--lg-magenta)" }}>
							{(result.total_rows ?? 0).toLocaleString()} ROWS
						</div>
						<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", marginTop: 6 }}>
							{result.tables_transformed} target tables · {result.encoding_conversions ?? 0} encoding fixes · {result.type_conversions ?? 0} type conversions
						</div>
						{result.warnings && result.warnings.length > 0 && (
							<div style={{ marginTop: 10, fontSize: 10, color: "var(--lg-warn)" }}>
								{result.warnings.length} warning(s) — see export step for details
							</div>
						)}
					</div>
				</div>
				<div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
					<button className="btn btn-ghost" onClick={() => { setResult(null); setSel(""); }}>
						RE-PICK STRATEGY
					</button>
					<button className="btn btn-primary pulse" onClick={onNext}>
						▶ EXPORT
					</button>
				</div>
			</div>
		);
	}

	return (
		<div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
			<div style={{ display: "flex", alignItems: "center", gap: 10 }}>
				<div className="pixel glow-cyan" style={{ fontSize: 11, color: "var(--lg-cyan)" }}>
					▣ CHOOSE YOUR STRATEGY
				</div>
				<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
					— each strategy converts your tables to a known target schema —
				</div>
				<div style={{ flex: 1 }} />
				<span className="badge badge-cyan">{items.length} STRATEGIES</span>
			</div>

			<div className="rl-strat-grid">
				{items.map((s) => {
					const m = meta(s);
					const active = s.id === sel;
					return (
						<div
							key={s.id}
							className={`rl-strat ${active ? "active" : ""}`}
							onClick={() => setSel(s.id)}
							style={{ ["--c" as string]: m.color } as React.CSSProperties}
						>
							<div className="rl-strat-tier" style={{ color: m.color }}>
								{m.tier}
							</div>
							<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
								<div className="rl-strat-icon" style={{ background: m.color }}>
									<IDisk size={20} />
								</div>
								<div>
									<div className="pixel" style={{ fontSize: 11, color: m.color, letterSpacing: "0.1em" }}>
										{s.name}
									</div>
									<div className="pixel" style={{ fontSize: 7, color: "var(--lg-ink-mute)", letterSpacing: "0.15em", marginTop: 4 }}>
										{m.tag}
									</div>
								</div>
							</div>
							<div className="mono" style={{ fontSize: 10.5, color: "var(--lg-ink-dim)", marginTop: 10, lineHeight: 1.5 }}>
								{m.desc}
							</div>
							<div className="rl-strat-stats">
								<div>
									<div className="lab pixel">TBLS</div>
									<div className="val pixel" style={{ color: m.color }}>{s.id === PASSTHROUGH_ID ? tables.length : s.table_count}</div>
								</div>
								<div>
									<div className="lab pixel">SIG</div>
									<div className="val pixel" style={{ color: m.color }}>{s.id === PASSTHROUGH_ID ? "—" : s.schema_signature.length}</div>
								</div>
								<div>
									<div className="lab pixel">TIER</div>
									<div className="val pixel" style={{ color: m.color }}>{m.tier}</div>
								</div>
								<div>
									<div className="lab pixel">FIT</div>
									<div className="val pixel" style={{ color: m.color }}>{s.id === PASSTHROUGH_ID ? "—" : "AUTO"}</div>
								</div>
							</div>
							{active && (
								<div className="rl-strat-eq">
									<span className="pixel" style={{ fontSize: 7, color: m.color }}>★ EQUIPPED</span>
								</div>
							)}
						</div>
					);
				})}
			</div>

			{error && (
				<div className="panel" style={{ borderColor: "var(--lg-coral)", padding: 12 }}>
					<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>
						{error}
					</div>
				</div>
			)}

			<div style={{ display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
				<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}>
					{selectedSummary ? (
						<>
							<span className="pixel" style={{ color: "var(--lg-cyan)" }}>SELECTED:</span> {selectedSummary.name}
						</>
					) : (
						<span className="pixel" style={{ color: "var(--lg-ink-mute)" }}>NO STRATEGY EQUIPPED</span>
					)}
				</div>
				<button
					className={`btn btn-primary ${sel && !running ? "pulse" : ""}`}
					disabled={!sel || running}
					onClick={runTransform}
				>
					{running ? "TRANSFORMING…" : "▶ RUN TRANSFORM"}
				</button>
			</div>
		</div>
	);
}


function RlExport({ onDone }: { onDone: () => void }) {
	const { projectId, uploadResult, transformResult, loadResult, setLoadResult } = usePipelineCtx();
	const [fmt, setFmt] = useState("json");
	const [running, setRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const excluded = useMemo(
		() => new Set(uploadResult?.excludedTables ?? []),
		[uploadResult?.excludedTables],
	);
	const visibleTables = (uploadResult?.tables ?? []).filter((t) => !excluded.has(t.name));
	const totalRows = transformResult?.total_rows ?? visibleTables.reduce((a, t) => a + t.rowCount, 0) ?? 0;

	const FORMATS = [
		{ id: "json", label: "JSON", sub: "One object per row" },
		{ id: "csv", label: "CSV", sub: "One file per table" },
		{ id: "sql", label: "SQL", sub: "CREATE + INSERT statements" },
	];

	const runLoad = async () => {
		if (!uploadResult?.sessionId) return;
		setRunning(true);
		setError(null);
		try {
			const res = await fetch(`/api/load/${uploadResult.sessionId}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({
					output_format: fmt,
					counter_resets: [],
					post_load_sql: [],
					use_staging: false,
					respect_fk_order: true,
				}),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || "Load failed");
			}
			const data = await res.json();
			setLoadResult(data);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Load failed");
		} finally {
			setRunning(false);
		}
	};

	return (
		<div
			style={{
				display: "grid",
				gridTemplateColumns: "240px 1fr 280px",
				gap: 14,
				marginTop: 14,
			}}
		>
			<div className="panel">
				<div className="panel-head">FORMAT</div>
				<div className="panel-body" style={{ padding: 0 }}>
					{FORMATS.map((f) => (
						<div
							key={f.id}
							onClick={() => {
								if (loadResult) setLoadResult(null);
								setFmt(f.id);
							}}
							className={`rl-fmt-row ${fmt === f.id ? "active" : ""}`}
						>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: fmt === f.id ? "#0a0410" : "var(--lg-amber)",
									letterSpacing: "0.1em",
								}}
							>
								{f.label}
							</div>
							<div
								className="mono"
								style={{
									fontSize: 10,
									color: fmt === f.id ? "#0a0410" : "var(--lg-ink-mute)",
									marginTop: 3,
								}}
							>
								{f.sub}
							</div>
						</div>
					))}
				</div>
			</div>

			<div className="panel">
				<div className="panel-head">
					<span style={{ flex: 1 }}>
						{loadResult ? "OUTPUT FILES" : "EXPORT SETTINGS"}
					</span>
					<span className="badge badge-mute">
						{totalRows.toLocaleString()} ROWS
					</span>
				</div>
				<div className="panel-body">
					{loadResult ? (
						<div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
							{loadResult.output_files.length > 1 && (
								<a
									href={projectId
										? `/api/projects/${projectId}/download-all`
										: `/api/download-all/${uploadResult?.sessionId}`}
									download
									className="btn btn-primary"
									style={{
										justifyContent: "center",
										marginBottom: 4,
									}}
								>
									⬇ DOWNLOAD ALL AS ZIP ({loadResult.output_files.length} FILES)
								</a>
							)}
							{loadResult.output_files.map((file) => (
								<div key={file} className="rl-file-row">
									<IDisk size={12} />
									<div style={{ flex: 1, fontSize: 12 }}>{file}</div>
									<a
										href={projectId
											? `/api/projects/${projectId}/download/${file}`
											: `/api/download/${uploadResult?.sessionId}/${file}`}
										download
										className="btn btn-ghost"
										style={{ padding: "4px 10px", fontSize: 10 }}
									>
										DOWNLOAD
									</a>
								</div>
							))}
							{loadResult.exceptions_written && loadResult.exceptions_written.length > 0 && (
								<div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid var(--lg-border)" }}>
									<div className="pixel" style={{ fontSize: 10, color: "var(--lg-amber)", marginBottom: 8 }}>
										REVIEW NEEDED
									</div>
									{loadResult.exceptions_written.map((file) => (
										<div key={file} className="rl-file-row" style={{ marginTop: 4 }}>
											<span style={{ fontSize: 9, color: "var(--lg-amber)" }}>⚠</span>
											<div style={{ flex: 1, fontSize: 12 }}>{file}</div>
											<a
												href={projectId
													? `/api/projects/${projectId}/download/${file}`
													: `/api/download/${uploadResult?.sessionId}/${file}`}
												download
												className="btn btn-ghost"
												style={{ padding: "4px 10px", fontSize: 10 }}
											>
												DOWNLOAD
											</a>
										</div>
									))}
								</div>
							)}
							{loadResult.errors.length > 0 && (
								<div style={{ marginTop: 8 }}>
									{loadResult.errors.map((e, i) => (
										<div
											key={i}
											className="mono"
											style={{ fontSize: 10, color: "var(--lg-coral)", marginTop: 4 }}
										>
											! {e}
										</div>
									))}
								</div>
							)}
							<div style={{ marginTop: 12 }}>
								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 8 }}
								>
									ROWS WRITTEN
								</div>
								<dl className="kv">
									{Object.entries(loadResult.rows_written).map(([table, count]) => (
										<>
											<dt key={table + "-dt"}>{table.toUpperCase()}</dt>
											<dd key={table + "-dd"}>{count.toLocaleString()}</dd>
										</>
									))}
								</dl>
							</div>
						</div>
					) : (
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-dim)",
								lineHeight: 1.7,
							}}
						>
							Select a format and click RUN to generate output files.
							The backend will process all transformed data and create
							downloadable {fmt.toUpperCase()} files.
						</div>
					)}
				</div>
			</div>

			<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">FINAL BOSS</div>
					<div className="panel-body">
						<div className="pixel glow-magenta" style={{ fontSize: 22, color: "var(--lg-magenta)" }}>
							{totalRows.toLocaleString()}
						</div>
						<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}>
							{loadResult ? "ROWS EXPORTED" : "ROWS WILL MIGRATE"}
						</div>
					</div>
				</div>
				<div className="panel">
					<div className="panel-head">OPTIONS</div>
					<div className="panel-body">
						<dl className="kv">
							<dt>FORMAT</dt>
							<dd>{fmt.toUpperCase()}</dd>
							<dt>ENCODING</dt>
							<dd>UTF-8</dd>
							<dt>ON ERROR</dt>
							<dd>halt + log</dd>
						</dl>
					</div>
				</div>

				{error && (
					<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>
						{"> "}{error}
					</div>
				)}

				{!loadResult ? (
					<button
						className={`btn btn-primary ${!running ? "pulse" : ""}`}
						onClick={runLoad}
						disabled={running || !uploadResult?.sessionId}
						style={{ fontSize: 13, padding: "12px 14px", justifyContent: "center" }}
					>
						{running ? "EXPORTING…" : "▶ EXPORT"}
					</button>
				) : (
					<button
						className="btn btn-primary"
						onClick={async () => {
							if (uploadResult?.sessionId) {
								try { await fetch(`/api/stats/${uploadResult.sessionId}`); } catch {}
							}
							onDone();
						}}
					>
						DONE · BACK TO PROJECTS
					</button>
				)}
			</div>
		</div>
	);
}

// ---------- pipeline wrapper ----------

export function RlPipeline({
	project,
	resumed,
	stage,
	setStage,
	onBack,
}: {
	project: Project | null;
	resumed: ResumedSession | null;
	stage: StageId;
	setStage: (s: StageId) => void;
	onBack: () => void;
}) {
	const next = () => {
		const i = RL_STAGES.findIndex((s) => s.id === stage);
		if (i < RL_STAGES.length - 1) setStage(RL_STAGES[i + 1].id);
	};
	const stageMeta = RL_STAGES.find((s) => s.id === stage);
	return (
		<PipelineProvider projectId={project?.id ?? null} resumed={resumed}>
			<div className="rl-page">
				<RlTopbar
					title={project?.name?.toUpperCase() || "PIPELINE"}
					sub={
						project
							? `PHASE: ${project.phase.toUpperCase()}`
							: "NOT STARTED"
					}
					right={
						<button className="btn btn-ghost" onClick={onBack}>
							← PROJECTS
						</button>
					}
				/>
				<RlStepper stage={stage} onStage={setStage} />
				<div
					className="pixel"
					style={{
						fontSize: 9,
						color: "var(--lg-ink-mute)",
						letterSpacing: "0.15em",
						margin: "16px 0 4px",
					}}
				>
					[ STAGE {RL_STAGES.findIndex((s) => s.id === stage) + 1}/6 ·{" "}
					{stageMeta?.label} · {stageMeta?.sub.toUpperCase()} ]
				</div>
				<div className="rl-stage" key={stage}>
					{stage === "upload" && <RlUpload onNext={next} />}
					{stage === "extract" && <RlExtract onNext={next} />}
					{stage === "transform" && <RlTransform onNext={next} />}
					{stage === "export" && <RlExport onDone={onBack} />}
				</div>
			</div>
		</PipelineProvider>
	);
}
