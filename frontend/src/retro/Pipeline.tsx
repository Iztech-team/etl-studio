import {
	createContext,
	Fragment,
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
import { RlAchievement } from "./XPBar";
import { useGlobalKeys, useKeyboardGrid } from "./keyboard";
import { CheatSheet } from "./CheatSheet";

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
	selectedEntities: string[];
};

type EntityDescriptor = {
	id: string;
	label: string;
	depends_on: string[];
};

type AuditCheck = {
	label: string;
	expected: number;
	actual: number;
	diff: number;
	status: "ok" | "over" | "short";
};
type AuditReport = {
	legacy_row_counts: Record<string, number>;
	output_doctype_counts: Record<string, number>;
	preserved: AuditCheck[];
	warnings_count: number;
	errors_count: number;
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
	strategy_name?: string | null;
	strategy_label?: string | null;
	strategy_stats?: Record<string, number>;
	output_doctypes?: Record<string, number>;
	audit_report?: AuditReport | null;
	setup_checklist_md?: string | null;
};

type StrategyConfigField = {
	type?: string;
	required?: boolean;
	default?: unknown;
	label?: string;
	help?: string;
};

type StrategyStats = {
	target_doctypes?: number;
	target_fields?: number;
	source_tables?: number;
	fit_score?: number;
};

type StrategyDescriptor = {
	name: string;
	label: string;
	description: string;
	config_schema: Record<string, StrategyConfigField>;
	tier?: string;
	kind?: string;
	stats?: StrategyStats;
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
	projectName: string | null;
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
	projectName,
	resumed,
	children,
}: {
	projectId: string | null;
	projectName: string | null;
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
			selectedEntities: resumed.selectedEntities ?? [],
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
			strategy_name: (t.strategy_name as string) ?? null,
			strategy_label: (t.strategy_label as string) ?? null,
			strategy_stats: (t.strategy_stats as Record<string, number>) ?? {},
			output_doctypes: (t.output_doctypes as Record<string, number>) ?? {},
			audit_report: (t.audit_report as AuditReport) ?? null,
			setup_checklist_md: (t.setup_checklist_md as string) ?? null,
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
		projectName,
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

// We're in the "uploading bytes" phase iff progress is non-null AND we
// haven't reached 100% yet. Once 100% is reached, the backend has the
// file and we hand off to the extraction phase.
function _isUploadingPhase(p: UploadProgress | null): boolean {
	if (!p) return false;
	if (p.total === 0) return true;
	return p.loaded < p.total;
}

function UploadProgressView({
	progress,
	fileCount,
}: {
	progress: UploadProgress;
	fileCount: number;
}) {
	const pct = progress.total > 0
		? Math.min(100, Math.floor((progress.loaded / progress.total) * 100))
		: 0;
	return (
		<>
			<div
				className="pixel"
				style={{ fontSize: 14, color: "var(--lg-amber)", letterSpacing: "0.15em" }}
			>
				UPLOADING…
			</div>
			<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}>
				{fileCount} FILE{fileCount === 1 ? "" : "S"} · {fmtSize(progress.loaded)} /{" "}
				{progress.total > 0 ? fmtSize(progress.total) : "…"}
			</div>
			<div
				style={{
					width: "100%",
					maxWidth: 360,
					height: 12,
					marginTop: 6,
					border: "1px solid var(--lg-border-br)",
					background: "var(--lg-bg-2)",
					position: "relative",
					overflow: "hidden",
				}}
			>
				<div
					style={{
						width: `${pct}%`,
						height: "100%",
						background: "var(--lg-amber)",
						transition: "width 120ms linear",
						boxShadow: "0 0 8px rgba(255,179,71,0.6)",
					}}
				/>
				<div
					className="pixel"
					style={{
						position: "absolute",
						top: 0,
						left: 0,
						right: 0,
						bottom: 0,
						display: "flex",
						alignItems: "center",
						justifyContent: "center",
						fontSize: 9,
						color: pct > 50 ? "#1a1006" : "var(--lg-ink)",
						mixBlendMode: pct > 50 ? "normal" : "normal",
						letterSpacing: "0.15em",
					}}
				>
					{pct}%
				</div>
			</div>
			<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginTop: 4 }}>
				Don't close this tab until the upload reaches 100%.
			</div>
		</>
	);
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
		selectedEntities: [],
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

type UploadProgress = { loaded: number; total: number };

// fetch() doesn't expose upload progress — XMLHttpRequest does. Wrap it
// in a fetch-shaped Promise<Response> so callers stay simple.
function xhrUpload(
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


async function uploadToBackend(
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
		selectedEntities: [],
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
					<div
						style={{
							marginLeft: "auto",
							fontFamily: "var(--lg-pixel)",
							fontSize: 8,
							color: i < idx ? "var(--lg-lime)" : "var(--lg-ink-mute)",
							letterSpacing: "0.1em",
						}}
					>
						+{s.xp}XP
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
	const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null);
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
		setUploadProgress({ loaded: 0, total: 0 });
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
				(p) => setUploadProgress(p),
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
					{uploading
						? _isUploadingPhase(uploadProgress)
							? "UPLOADING TO SERVER"
							: "EXTRACTING DATABASE"
						: "UPLOAD DATA FILES"}
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
							{_isUploadingPhase(uploadProgress) ? (
								<UploadProgressView progress={uploadProgress!} fileCount={staged.length} />
							) : (
								<>
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
								<>
									<div
										className="mono"
										style={{ fontSize: 11, color: "var(--lg-ink-mute)" }}
									>
										{staged.some((s) => isDbFile(s.file.name))
											? "Connecting to database…"
											: "Processing files server-side…"}
									</div>
									<div
										className="mono"
										style={{ fontSize: 10, color: "var(--lg-ink-mute)", maxWidth: 360, lineHeight: 1.5 }}
									>
										Reading and indexing your data into staging files. Large
										uploads take a moment.
									</div>
								</>
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
								</>
								)}
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
	const { uploadResult, setUploadResult, setTransformResult, setLoadResult } =
		usePipelineCtx();
	const [entities, setEntities] = useState<EntityDescriptor[] | null>(null);
	const [picks, setPicks] = useState<Set<string>>(new Set());
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		fetch("/api/entities")
			.then((r) => r.json())
			.then((d) => {
				if (cancelled) return;
				const list = (d.entities ?? []) as EntityDescriptor[];
				setEntities(list);
				const prev = uploadResult?.selectedEntities ?? [];
				setPicks(prev.length > 0
					? new Set(prev)
					: new Set(list.map((e) => e.id)));
			})
			.catch((e) => { if (!cancelled) setError(String(e)); });
		return () => { cancelled = true; };
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const effective = useMemo(
		() => (entities ? resolveEntityDeps(picks, entities) : new Set<string>()),
		[picks, entities],
	);

	const labelMap = useMemo(
		() => Object.fromEntries((entities ?? []).map((e) => [e.id, e.label])),
		[entities],
	);

	if (!entities) {
		return (
			<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", padding: 24 }}>
				Loading entities…
			</div>
		);
	}

	const togglePick = (id: string) => {
		setPicks((prev) => {
			const next = new Set(prev);
			if (next.has(id)) {
				next.delete(id);
				for (const dep of entityDependents(id, entities)) next.delete(dep);
			} else {
				next.add(id);
			}
			return next;
		});
	};

	const proceed = async () => {
		const sid = uploadResult?.sessionId;
		if (!sid) return;
		setSaving(true);
		setError(null);
		try {
			const res = await fetch(`/api/select-entities/${sid}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ entities: Array.from(picks) }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail ?? "Selection failed");
			}
			const data = (await res.json()) as { selected: string[]; changed: boolean };
			if (uploadResult) {
				setUploadResult({ ...uploadResult, selectedEntities: data.selected });
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
		<div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
			<div style={{ display: "flex", alignItems: "center", gap: 12 }}>
				<div className="pixel glow-amber" style={{ fontSize: 11, color: "var(--lg-amber)" }}>
					▣ EXTRACT — pick what to migrate
				</div>
				<div style={{ flex: 1 }} />
				<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
					{effective.size} of {entities.length} selected
				</div>
			</div>

			<div
				style={{
					display: "grid",
					gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
					gap: 10,
				}}
			>
				{entities.map((e) => {
					const userPicked = picks.has(e.id);
					const forced = !userPicked && effective.has(e.id);
					return (
						<EntityCard
							key={e.id}
							entity={e}
							picked={userPicked}
							forced={forced}
							depLabels={e.depends_on.map((d) => labelMap[d] ?? d)}
							onToggle={() => togglePick(e.id)}
						/>
					);
				})}
			</div>

			{error && (
				<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>
					{"> "}{error}
				</div>
			)}

			<div style={{ display: "flex", justifyContent: "flex-end" }}>
				<button
					className="btn btn-primary"
					onClick={proceed}
					disabled={effective.size === 0 || saving || !uploadResult?.sessionId}
				>
					{saving ? "SAVING…" : "CONTINUE TO TRANSFORM"} <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}


function EntityCard({
	entity,
	picked,
	forced,
	depLabels,
	onToggle,
}: {
	entity: EntityDescriptor;
	picked: boolean;
	forced: boolean;
	depLabels: string[];
	onToggle: () => void;
}) {
	const active = picked || forced;
	return (
		<button
			onClick={forced ? undefined : onToggle}
			className="btn"
			disabled={forced}
			title={forced ? "Auto-included as a dependency" : ""}
			style={{
				textAlign: "left",
				padding: "12px 14px",
				borderColor: active ? "var(--lg-amber)" : "var(--lg-border-br)",
				background: forced
					? "rgba(199,155,0,0.04)"
					: picked
					? "rgba(199,155,0,0.08)"
					: "transparent",
				opacity: forced ? 0.7 : 1,
				cursor: forced ? "not-allowed" : "pointer",
				display: "flex",
				flexDirection: "column",
				gap: 6,
				textTransform: "none",
				letterSpacing: 0,
			}}
		>
			<div style={{ display: "flex", alignItems: "center", gap: 10 }}>
				<span
					style={{
						display: "inline-flex",
						alignItems: "center",
						justifyContent: "center",
						width: 14,
						height: 14,
						border: "1px solid var(--lg-amber)",
						background: active ? "var(--lg-amber)" : "transparent",
						color: "#0a0410",
						flexShrink: 0,
					}}
				>
					{active && <ICheck size={8} />}
				</span>
				<span
					className="pixel"
					style={{
						fontSize: 12,
						color: active ? "var(--lg-amber)" : "var(--lg-ink)",
						letterSpacing: "0.05em",
					}}
				>
					{entity.label.toUpperCase()}
				</span>
			</div>
			{forced ? (
				<span className="mono" style={{ fontSize: 9, color: "var(--lg-ink-mute)" }}>
					auto-included
				</span>
			) : depLabels.length > 0 ? (
				<span className="mono" style={{ fontSize: 9, color: "var(--lg-ink-dim)" }}>
					requires: {depLabels.join(", ")}
				</span>
			) : null}
		</button>
	);
}


function resolveEntityDeps(picks: Set<string>, all: EntityDescriptor[]): Set<string> {
	const out = new Set(picks);
	let changed = true;
	while (changed) {
		changed = false;
		for (const e of all) {
			if (!out.has(e.id)) continue;
			for (const d of e.depends_on) {
				if (!out.has(d)) {
					out.add(d);
					changed = true;
				}
			}
		}
	}
	return out;
}


function entityDependents(id: string, all: EntityDescriptor[]): Set<string> {
	const out = new Set<string>();
	let changed = true;
	while (changed) {
		changed = false;
		for (const e of all) {
			if (out.has(e.id)) continue;
			for (const dep of e.depends_on) {
				if (dep === id || out.has(dep)) {
					out.add(e.id);
					changed = true;
					break;
				}
			}
		}
	}
	return out;
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

// ---------- transform ----------
// Strategy-driven transform UI:
//   1) load /api/strategies  → pick strategy
//   2) edit config (form derived from the strategy's config_schema)
//   3) save to /api/strategies/{sid}; trigger /api/transform/{sid}
//   4) show preservation audit + per-doctype counts

function RlTransform({ onNext }: { onNext: () => void }) {
	const { uploadResult, transformResult, setTransformResult, projectId, projectName } =
		usePipelineCtx();
	const [strategies, setStrategies] = useState<StrategyDescriptor[] | null>(null);
	const [loadErr, setLoadErr] = useState<string | null>(null);
	const [pickedName, setPickedName] = useState<string | null>(null);
	const [config, setConfig] = useState<Record<string, unknown>>({});
	const [running, setRunning] = useState(false);
	const [runErr, setRunErr] = useState<string | null>(null);
	const [result, setResult] = useState<TransformResult | null>(transformResult ?? null);
	// Strategy is only "equipped" once the user fills out config in the modal
	// and confirms — that's when pickedName + config get committed. Until
	// then we hold a draft so cancel doesn't clobber the active equip.
	const [configModalFor, setConfigModalFor] = useState<string | null>(null);
	const [draftConfig, setDraftConfig] = useState<Record<string, unknown>>({});

	useEffect(() => {
		let cancelled = false;
		const run = async () => {
			try {
				const res = await fetch("/api/strategies");
				if (!res.ok) throw new Error("strategies endpoint unavailable");
				const json = await res.json();
				if (cancelled) return;
				const list = (json.strategies ?? []) as StrategyDescriptor[];
				setStrategies(list);
			} catch (e) {
				if (!cancelled) setLoadErr(e instanceof Error ? e.message : "load failed");
			}
		};
		run();
		return () => {
			cancelled = true;
		};
	}, []);

	const picked = strategies?.find((s) => s.name === pickedName) ?? null;
	const missingFields = picked ? requiredMissing(picked.config_schema, config) : [];

	const openConfigModal = (name: string) => {
		const s = strategies?.find((x) => x.name === name);
		if (!s) return;
		// Re-editing the equipped strategy keeps the existing config; picking
		// a fresh one starts from smartDefaults so the user doesn't lose
		// values they just set on a different strategy mid-flow.
		setDraftConfig(
			pickedName === name
				? config
				: smartDefaults(s.config_schema, projectName),
		);
		setConfigModalFor(name);
	};

	const equipStrategy = () => {
		if (!configModalFor) return;
		setPickedName(configModalFor);
		setConfig(draftConfig);
		setConfigModalFor(null);
	};

	const cancelConfigModal = () => setConfigModalFor(null);

	const modalStrategy =
		(configModalFor && strategies?.find((s) => s.name === configModalFor)) || null;

	const runTransform = async () => {
		if (!uploadResult?.sessionId || !pickedName) return;
		setRunning(true);
		setRunErr(null);
		const lsKey = ACTIVE_TRANSFORM_LS_PREFIX + (projectId ?? "guest");
		try {
			localStorage.setItem(
				lsKey,
				JSON.stringify({ sessionId: uploadResult.sessionId, projectId }),
			);
		} catch {}
		try {
			const sid = uploadResult.sessionId;
			const saveRes = await fetch(`/api/strategies/${sid}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ strategy_name: pickedName, config }),
			});
			if (!saveRes.ok) {
				const err = await saveRes.json().catch(() => null);
				throw new Error(err?.detail || "Could not save strategy config");
			}
			const runRes = await fetch(`/api/transform/${sid}`);
			if (!runRes.ok) {
				const err = await runRes.json().catch(() => null);
				throw new Error(err?.detail || "Transform failed");
			}
			const data = (await runRes.json()) as TransformResult;
			setResult(data);
			setTransformResult(data);
		} catch (e) {
			setRunErr(e instanceof Error ? e.message : "Transform failed");
		} finally {
			try {
				localStorage.removeItem(lsKey);
			} catch {}
			setRunning(false);
		}
	};

	if (result) {
		return (
			<TransformResultView
				result={result}
				onReRun={() => setResult(null)}
				onNext={onNext}
			/>
		);
	}

	return (
		<div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
			<TransformHeader />

			{loadErr && <RlErrorPanel message={loadErr} />}

			{!strategies && !loadErr && (
				<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}>
					Loading strategies…
				</div>
			)}

			{strategies && strategies.length === 0 && (
				<RlErrorPanel message="No transform strategies registered on the backend." />
			)}

			{strategies && strategies.length > 0 && (
				<>
					<StrategyPicker
						strategies={strategies}
						pickedName={pickedName}
						onPick={openConfigModal}
					/>
					{runErr && <RlErrorPanel message={runErr} />}
					{running && <TransformRunningPanel />}
					<TransformActions
						disabled={running || !uploadResult?.sessionId || !pickedName || missingFields.length > 0}
						running={running}
						missingFields={missingFields}
						onRun={runTransform}
						picked={picked}
						onEditConfig={pickedName ? () => openConfigModal(pickedName) : undefined}
					/>
				</>
			)}

			{modalStrategy && (
				<StrategyConfigModal
					strategy={modalStrategy}
					config={draftConfig}
					onChange={setDraftConfig}
					onEquip={equipStrategy}
					onCancel={cancelConfigModal}
				/>
			)}
		</div>
	);
}

function TransformRunningPanel() {
	const PHASES = [
		"Reading legacy tables…",
		"Building items + barcodes…",
		"Resolving customers and suppliers…",
		"Walking chart of accounts…",
		"Aggregating sales invoices…",
		"Streaming output to disk…",
	];
	const [phase, setPhase] = useState(0);
	const [pulseOffset, setPulseOffset] = useState(0);
	useEffect(() => {
		const phaseTimer = window.setInterval(
			() => setPhase((p) => (p + 1) % PHASES.length),
			2400,
		);
		const pulseTimer = window.setInterval(
			() => setPulseOffset((o) => (o + 6) % 60),
			60,
		);
		return () => {
			window.clearInterval(phaseTimer);
			window.clearInterval(pulseTimer);
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);
	return (
		<div className="panel" style={{ borderColor: "var(--lg-magenta)" }}>
			<div className="panel-head">
				<span className="pixel glow-magenta" style={{ color: "var(--lg-magenta)" }}>
					▣ TRANSFORM IN PROGRESS
				</span>
			</div>
			<div
				className="panel-body"
				style={{
					display: "flex",
					flexDirection: "column",
					alignItems: "center",
					gap: 14,
					padding: "26px 20px",
				}}
			>
				<div className="sprite-disk" />
				<div
					className="pixel"
					style={{ fontSize: 13, color: "var(--lg-magenta)", letterSpacing: "0.15em" }}
				>
					{PHASES[phase]}
				</div>
				<div
					style={{
						width: "100%",
						maxWidth: 380,
						height: 10,
						border: "1px solid var(--lg-border-br)",
						background: "var(--lg-bg-2)",
						overflow: "hidden",
						position: "relative",
					}}
				>
					<div
						style={{
							position: "absolute",
							top: 0,
							bottom: 0,
							left: `${pulseOffset - 30}%`,
							width: "30%",
							background:
								"linear-gradient(90deg, transparent, var(--lg-magenta), transparent)",
							boxShadow: "0 0 12px rgba(176,102,255,0.6)",
						}}
					/>
				</div>
				<div
					className="mono"
					style={{
						fontSize: 10,
						color: "var(--lg-ink-mute)",
						maxWidth: 380,
						lineHeight: 1.5,
						textAlign: "center",
					}}
				>
					Output streams to disk during transform — peak memory stays
					bounded so large datasets don't OOM. Don't close this tab.
				</div>
			</div>
		</div>
	);
}

// -- transform sub-components ------------------------------------------------

function TransformHeader() {
	return (
		<div style={{ display: "flex", alignItems: "center", gap: 10 }}>
			<div className="pixel glow-cyan" style={{ fontSize: 11, color: "var(--lg-cyan)" }}>
				▣ TRANSFORM
			</div>
			<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
				— pick a strategy, set config, run —
			</div>
		</div>
	);
}

function RlErrorPanel({ message }: { message: string }) {
	return (
		<div className="panel" style={{ borderColor: "var(--lg-coral)", padding: 12 }}>
			<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>{message}</div>
		</div>
	);
}

function StrategyPicker({
	strategies,
	pickedName,
	onPick,
}: {
	strategies: StrategyDescriptor[];
	pickedName: string | null;
	onPick: (name: string) => void;
}) {
	const cols = strategies.length === 1 ? 1 : strategies.length === 2 ? 2 : 3;
	return (
		<div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
			<StrategyPickerHeader count={strategies.length} />
			<div
				style={{
					display: "grid",
					gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))`,
					gap: 12,
				}}
			>
				{strategies.map((s) => (
					<StrategyCard
						key={s.name}
						strategy={s}
						active={s.name === pickedName}
						onPick={() => onPick(s.name)}
					/>
				))}
			</div>
		</div>
	);
}

function StrategyPickerHeader({ count }: { count: number }) {
	return (
		<div style={{ display: "flex", alignItems: "center", gap: 12 }}>
			<div className="pixel glow-cyan" style={{ fontSize: 11, color: "var(--lg-cyan)" }}>
				▣ CHOOSE YOUR STRATEGY
			</div>
			<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
				— each strategy converts your tables to a known target schema —
			</div>
			<div style={{ flex: 1 }} />
			<div
				className="pixel"
				style={{
					fontSize: 9,
					color: "var(--lg-ink-mute)",
					letterSpacing: "0.15em",
					padding: "3px 8px",
					border: "1px solid var(--lg-border-br)",
				}}
			>
				{count} STRATEGY{count === 1 ? "" : "S"}
			</div>
		</div>
	);
}

function StrategyCard({
	strategy,
	active,
	onPick,
}: {
	strategy: StrategyDescriptor;
	active: boolean;
	onPick: () => void;
}) {
	const stats = strategy.stats ?? {};
	const tier = strategy.tier || "";
	return (
		<button
			onClick={onPick}
			className="btn"
			style={{
				position: "relative",
				textAlign: "left",
				padding: "14px 14px 12px",
				borderColor: active ? "var(--lg-magenta)" : "var(--lg-border-br)",
				background: active ? "rgba(176,102,255,0.06)" : "transparent",
				boxShadow: active ? "0 0 14px rgba(176,102,255,0.4)" : "none",
				display: "flex",
				flexDirection: "column",
				gap: 10,
				textTransform: "none",
				letterSpacing: 0,
				minHeight: 200,
			}}
		>
			{tier && <StrategyTierBadge tier={tier} active={active} />}
			<div style={{ display: "flex", alignItems: "flex-start", gap: 10 }}>
				<StrategyPickIndicator active={active} />
				<div style={{ display: "flex", flexDirection: "column", gap: 2, flex: 1 }}>
					<div className="pixel glow-magenta" style={{ fontSize: 14, color: "var(--lg-magenta)" }}>
						{strategy.label.toUpperCase()}
					</div>
					<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.15em" }}>
						{(strategy.kind || "GENERIC").toUpperCase()}
					</div>
				</div>
			</div>
			<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", lineHeight: 1.5 }}>
				{strategy.description}
			</div>
			<StrategyStatRow stats={stats} active={active} />
			{active && (
				<div
					className="pixel"
					style={{
						alignSelf: "flex-end",
						fontSize: 8,
						color: "var(--lg-magenta)",
						letterSpacing: "0.2em",
					}}
				>
					· EQUIPPED
				</div>
			)}
		</button>
	);
}

function StrategyTierBadge({ tier, active }: { tier: string; active: boolean }) {
	const color = active ? "var(--lg-magenta)" : "var(--lg-border-br)";
	return (
		<div
			className="pixel"
			style={{
				position: "absolute",
				top: 8,
				right: 8,
				fontSize: 9,
				color,
				border: `1px solid ${color}`,
				padding: "1px 6px",
				letterSpacing: "0.1em",
			}}
		>
			{tier}
		</div>
	);
}

function StrategyPickIndicator({ active }: { active: boolean }) {
	return (
		<span
			style={{
				display: "inline-block",
				width: 14,
				height: 14,
				marginTop: 2,
				border: `1px solid ${active ? "var(--lg-magenta)" : "var(--lg-border-br)"}`,
				background: active ? "var(--lg-magenta)" : "transparent",
				flexShrink: 0,
			}}
		/>
	);
}

function StrategyStatRow({
	stats,
	active,
}: {
	stats: StrategyStats;
	active: boolean;
}) {
	const valueColor = active ? "var(--lg-magenta)" : "var(--lg-ink)";
	return (
		<div
			style={{
				display: "grid",
				gridTemplateColumns: "repeat(4, 1fr)",
				gap: 4,
				borderTop: "1px solid var(--lg-border)",
				paddingTop: 10,
			}}
		>
			<StrategyStat label="TBLS" value={stats.target_doctypes} valueColor={valueColor} />
			<StrategyStat label="FLDS" value={stats.target_fields} valueColor={valueColor} />
			<StrategyStat
				label="USED"
				value={stats.source_tables ? `${stats.source_tables}×` : undefined}
				valueColor={valueColor}
			/>
			<StrategyStat
				label="FIT"
				value={stats.fit_score != null ? `${stats.fit_score}%` : undefined}
				valueColor={valueColor}
			/>
		</div>
	);
}

function StrategyStat({
	label,
	value,
	valueColor,
}: {
	label: string;
	value: number | string | undefined;
	valueColor: string;
}) {
	return (
		<div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
			<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.15em" }}>
				{label}
			</div>
			<div className="pixel" style={{ fontSize: 14, color: valueColor }}>
				{value ?? "—"}
			</div>
		</div>
	);
}

function StrategyConfigForm({
	schema,
	value,
	onChange,
}: {
	schema: Record<string, StrategyConfigField>;
	value: Record<string, unknown>;
	onChange: (next: Record<string, unknown>) => void;
}) {
	const entries = Object.entries(schema);
	if (entries.length === 0) return null;
	return (
		<div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
			{entries.map(([key, field]) => (
				<ConfigField
					key={key}
					name={key}
					field={field}
					value={value[key]}
					onChange={(v) => onChange({ ...value, [key]: v })}
				/>
			))}
		</div>
	);
}

function ConfigField({
	name,
	field,
	value,
	onChange,
}: {
	name: string;
	field: StrategyConfigField;
	value: unknown;
	onChange: (v: unknown) => void;
}) {
	const label = field.label ?? name;
	const required = !!field.required;
	const help = field.help;
	const type = field.type ?? "string";

	if (type === "boolean") {
		return (
			<label
				className="mono"
				title={help}
				style={{
					display: "flex",
					alignItems: "center",
					gap: 10,
					fontSize: 12,
					color: "var(--lg-ink)",
				}}
			>
				<input
					type="checkbox"
					checked={!!value}
					onChange={(e) => onChange(e.target.checked)}
				/>
				<span>
					{label}
					{required ? " *" : ""}
				</span>
			</label>
		);
	}

	return (
		<label
			title={help}
			style={{ display: "flex", flexDirection: "column", gap: 4 }}
		>
			<span
				className="pixel"
				style={{ fontSize: 9, color: "var(--lg-ink-mute)", letterSpacing: "0.1em" }}
			>
				{label}
				{required ? " *" : ""}
			</span>
			<input
				type={type === "date" ? "date" : "text"}
				className="mono"
				value={(value as string | number | undefined) ?? ""}
				onChange={(e) => onChange(e.target.value)}
				style={{
					background: "var(--lg-bg-2)",
					border: "1px solid var(--lg-border-br)",
					color: "var(--lg-ink)",
					padding: "8px 10px",
					fontSize: 12,
				}}
			/>
		</label>
	);
}

function TransformActions({
	disabled,
	running,
	missingFields,
	onRun,
	picked,
	onEditConfig,
}: {
	disabled: boolean;
	running: boolean;
	missingFields: string[];
	onRun: () => void;
	picked: StrategyDescriptor | null;
	onEditConfig?: () => void;
}) {
	const stats = picked?.stats ?? {};
	const summary = picked
		? [
				picked.name.toUpperCase(),
				stats.target_doctypes != null ? `${stats.target_doctypes} tables` : null,
				stats.target_fields != null ? `${stats.target_fields} fields` : null,
		  ]
				.filter(Boolean)
				.join(" · ")
		: "—";
	return (
		<div
			style={{
				display: "flex",
				justifyContent: "space-between",
				alignItems: "center",
				gap: 12,
				borderTop: "1px solid var(--lg-border)",
				paddingTop: 14,
				marginTop: 4,
			}}
		>
			<div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
				<div className="pixel" style={{ fontSize: 9, color: "var(--lg-ink-mute)", letterSpacing: "0.15em" }}>
					EQUIPPED:
				</div>
				<div className="mono" style={{ fontSize: 12, color: "var(--lg-ink)" }}>
					{picked ? summary : "— pick a strategy above —"}
				</div>
				{missingFields.length > 0 && (
					<div className="mono" style={{ fontSize: 10, color: "var(--lg-coral)" }}>
						Missing: {missingFields.join(", ")}
					</div>
				)}
			</div>
			<div style={{ display: "flex", gap: 8 }}>
				{picked && onEditConfig && (
					<button
						className="btn btn-ghost"
						onClick={onEditConfig}
						style={{ fontSize: 11, padding: "12px 16px" }}
					>
						EDIT CONFIG
					</button>
				)}
				<button
					className={`btn btn-primary ${!disabled ? "pulse" : ""}`}
					disabled={disabled}
					onClick={onRun}
					style={{ fontSize: 12, padding: "12px 24px" }}
				>
					{running ? "TRANSFORMING…" : "▶ TRANSFORM"}
				</button>
			</div>
		</div>
	);
}


function StrategyConfigModal({
	strategy,
	config,
	onChange,
	onEquip,
	onCancel,
}: {
	strategy: StrategyDescriptor;
	config: Record<string, unknown>;
	onChange: (next: Record<string, unknown>) => void;
	onEquip: () => void;
	onCancel: () => void;
}) {
	const missing = requiredMissing(strategy.config_schema, config);
	const hasFields = Object.keys(strategy.config_schema).length > 0;

	useEffect(() => {
		const onKey = (e: KeyboardEvent) => {
			if (e.key === "Escape") onCancel();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [onCancel]);

	return (
		<div
			style={{
				position: "fixed",
				inset: 0,
				zIndex: 9999,
				background: "rgba(0,0,0,0.75)",
				display: "flex",
				alignItems: "center",
				justifyContent: "center",
				padding: 24,
			}}
			onClick={onCancel}
		>
			<div
				style={{
					background: "var(--lg-bg)",
					border: "2px solid var(--lg-magenta)",
					width: 420,
					maxWidth: "92vw",
					maxHeight: "90vh",
					display: "flex",
					flexDirection: "column",
				}}
				onClick={(e) => e.stopPropagation()}
			>
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
							color: "var(--lg-magenta)",
							letterSpacing: "0.1em",
						}}
					>
						{strategy.label.toUpperCase()}
					</span>
					<button
						className="btn btn-ghost"
						style={{ padding: "2px 6px", fontSize: 10 }}
						onClick={onCancel}
					>
						<IX size={10} />
					</button>
				</div>

				<div style={{ padding: "16px 14px", overflowY: "auto" }}>
					{hasFields ? (
						<StrategyConfigForm
							schema={strategy.config_schema}
							value={config}
							onChange={onChange}
						/>
					) : (
						<div
							className="mono"
							style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}
						>
							No configuration needed.
						</div>
					)}
				</div>

				<div
					style={{
						display: "flex",
						justifyContent: "flex-end",
						gap: 8,
						padding: "10px 14px",
						borderTop: "1px solid var(--lg-border)",
					}}
				>
					<button
						className="btn btn-ghost"
						style={{ padding: "6px 14px", fontSize: 11 }}
						onClick={onCancel}
					>
						CANCEL
					</button>
					<button
						className="btn btn-primary"
						style={{ padding: "6px 16px", fontSize: 11 }}
						onClick={onEquip}
						disabled={missing.length > 0}
					>
						EQUIP
					</button>
				</div>
			</div>
		</div>
	);
}

function TransformResultView({
	result,
	onReRun,
	onNext,
}: {
	result: TransformResult;
	onReRun: () => void;
	onNext: () => void;
}) {
	const audit = result.audit_report ?? null;
	const docs = result.output_doctypes ?? {};
	const docEntries = Object.entries(docs).sort((a, b) => b[1] - a[1]);
	return (
		<div style={{ marginTop: 14, display: "flex", flexDirection: "column", gap: 14 }}>
			<div className="panel">
				<div className="panel-head">▼ TRANSFORM COMPLETE</div>
				<div className="panel-body" style={{ display: "flex", gap: 24, alignItems: "center" }}>
					<TransformBigStat label="ROWS" value={(result.total_rows ?? 0).toLocaleString()} />
					<TransformBigStat label="DOCTYPES" value={String(result.tables_transformed ?? 0)} />
					<div style={{ flex: 1 }} />
					<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", maxWidth: 320, lineHeight: 1.5 }}>
						Strategy: <strong>{result.strategy_label || result.strategy_name || "—"}</strong>
						{audit && (
							<>
								<br />
								Warnings: {audit.warnings_count} · Errors: {audit.errors_count}
							</>
						)}
					</div>
				</div>
			</div>

			{docEntries.length > 0 && (
				<div className="panel">
					<div className="panel-head">DOCTYPE OUTPUT</div>
					<div
						className="panel-body"
						style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8 }}
					>
						{docEntries.map(([name, count]) => (
							<div
								key={name}
								className="mono"
								style={{
									display: "flex",
									justifyContent: "space-between",
									gap: 12,
									padding: "6px 10px",
									border: "1px solid var(--lg-border)",
									fontSize: 11,
								}}
							>
								<span style={{ color: "var(--lg-ink)" }}>{name}</span>
								<span style={{ color: "var(--lg-magenta)", fontVariantNumeric: "tabular-nums" }}>
									{count.toLocaleString()}
								</span>
							</div>
						))}
					</div>
				</div>
			)}

			{audit && audit.preserved.length > 0 && (
				<div className="panel">
					<div className="panel-head">PRESERVATION AUDIT</div>
					<div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
						{audit.preserved.map((c) => (
							<AuditRow key={c.label} check={c} />
						))}
					</div>
				</div>
			)}

			{result.warnings && result.warnings.length > 0 && (
				<div className="panel" style={{ borderColor: "var(--lg-amber)" }}>
					<div className="panel-head">WARNINGS ({result.warnings.length})</div>
					<div className="panel-body" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
						{result.warnings.map((w, i) => (
							<div key={i} className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
								— {w}
							</div>
						))}
					</div>
				</div>
			)}

			{result.setup_checklist_md && <SetupChecklistPanel md={result.setup_checklist_md} />}

			<div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
				<button className="btn btn-ghost" onClick={onReRun}>RE-RUN</button>
				<button className="btn btn-primary pulse" onClick={onNext}>▶ EXPORT</button>
			</div>
		</div>
	);
}

function TransformBigStat({ label, value }: { label: string; value: string }) {
	return (
		<div>
			<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.15em", marginBottom: 4 }}>
				{label}
			</div>
			<div className="pixel glow-magenta" style={{ fontSize: 22, color: "var(--lg-magenta)" }}>
				{value}
			</div>
		</div>
	);
}

function AuditRow({ check }: { check: AuditCheck }) {
	const okColor = "var(--lg-cyan)";
	const failColor = "var(--lg-coral)";
	const warnColor = "var(--lg-magenta)";
	const tone =
		check.status === "ok"
			? { dot: okColor, label: "OK" }
			: check.status === "short"
				? { dot: failColor, label: check.status.toUpperCase() }
				: { dot: warnColor, label: check.status.toUpperCase() };
	return (
		<div className="mono" style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 11 }}>
			<span
				style={{
					display: "inline-block",
					minWidth: 44,
					textAlign: "center",
					padding: "1px 6px",
					border: `1px solid ${tone.dot}`,
					color: tone.dot,
					fontSize: 9,
					letterSpacing: "0.1em",
				}}
			>
				{tone.label}
			</span>
			<span style={{ flex: 1, color: "var(--lg-ink)" }}>{check.label}</span>
			<span style={{ color: "var(--lg-ink-dim)", fontVariantNumeric: "tabular-nums" }}>
				{check.expected.toLocaleString()} → {check.actual.toLocaleString()}
			</span>
			<span style={{ color: tone.dot, fontVariantNumeric: "tabular-nums", minWidth: 56, textAlign: "right" }}>
				{check.diff >= 0 ? `+${check.diff}` : check.diff}
			</span>
		</div>
	);
}

function SetupChecklistPanel({ md }: { md: string }) {
	const [open, setOpen] = useState(false);
	return (
		<div className="panel">
			<div className="panel-head" style={{ display: "flex", alignItems: "center" }}>
				<span>MIGRATION SETUP CHECKLIST</span>
				<span style={{ flex: 1 }} />
				<button className="link" onClick={() => setOpen((v) => !v)}>
					{open ? "hide" : "show"} ↗
				</button>
			</div>
			{open && (
				<pre
					className="mono"
					style={{
						margin: 0,
						padding: 14,
						fontSize: 10,
						color: "var(--lg-ink-dim)",
						whiteSpace: "pre-wrap",
						maxHeight: 380,
						overflow: "auto",
					}}
				>
					{md}
				</pre>
			)}
		</div>
	);
}

// -- helpers ------------------------------------------------------------------

function defaultsForSchema(
	schema: Record<string, StrategyConfigField>,
): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	for (const [key, f] of Object.entries(schema)) {
		if (f.default !== undefined) out[key] = f.default;
		else if (f.type === "boolean") out[key] = false;
		else out[key] = "";
	}
	return out;
}

// Layer in sensible defaults derived from the project so the user only has
// to confirm. Project name → company; initials → abbreviation; today → opening.
function smartDefaults(
	schema: Record<string, StrategyConfigField>,
	projectName: string | null,
): Record<string, unknown> {
	const out = defaultsForSchema(schema);
	if ("company_name" in schema && !out.company_name && projectName) {
		out.company_name = humanizeProjectName(projectName);
	}
	if ("company_abbr" in schema && !out.company_abbr && projectName) {
		out.company_abbr = abbrFromName(projectName);
	}
	if ("opening_date" in schema && !out.opening_date) {
		out.opening_date = new Date().toISOString().slice(0, 10);
	}
	return out;
}

function humanizeProjectName(raw: string): string {
	const cleaned = raw.replace(/[-_]+/g, " ").trim();
	return cleaned
		.split(/\s+/)
		.map((w) => (w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w))
		.join(" ");
}

function abbrFromName(raw: string): string {
	const parts = raw.replace(/[-_]+/g, " ").trim().split(/\s+/).filter(Boolean);
	if (parts.length === 0) return "ALA";
	if (parts.length === 1) return parts[0].slice(0, 3).toUpperCase();
	return parts.map((p) => p[0]).join("").slice(0, 4).toUpperCase();
}

function requiredMissing(
	schema: Record<string, StrategyConfigField>,
	value: Record<string, unknown>,
): string[] {
	const missing: string[] = [];
	for (const [key, f] of Object.entries(schema)) {
		if (!f.required) continue;
		const v = value[key];
		if (v === undefined || v === null || v === "") missing.push(f.label ?? key);
	}
	return missing;
}

function RlExport({ onDone }: { onDone: () => void }) {
	const { projectId, uploadResult, transformResult, loadResult, setLoadResult } = usePipelineCtx();
	// `transformResult` alone is enough to know a strategy ran — every
	// transform in the current pipeline is a strategy-driven one. Falling
	// back to `strategy_name` was unreliable because older persisted
	// project state didn't always round-trip that field, and the Frappe
	// CSV option would silently disappear.
	const usedStrategy = !!transformResult;
	const [fmt, setFmt] = useState(usedStrategy ? "frappe" : "json");
	const [running, setRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);

	// On entry, drop any persisted loadResult so the user doesn't see
	// stale output files from a previous run when reopening a project.
	// They'll click EXPORT to regenerate against the current session.
	useEffect(() => {
		setLoadResult(null);
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	const excluded = useMemo(
		() => new Set(uploadResult?.excludedTables ?? []),
		[uploadResult?.excludedTables],
	);
	const visibleTables = (uploadResult?.tables ?? []).filter((t) => !excluded.has(t.name));
	const totalRows = transformResult?.total_rows ?? visibleTables.reduce((a, t) => a + t.rowCount, 0) ?? 0;

	const FORMATS = usedStrategy
		? [
			{ id: "frappe", label: "FRAPPE CSV", sub: "ERPnext Data Import (chunked, ordered)" },
			{ id: "json",   label: "JSON",       sub: "One object per row" },
			{ id: "csv",    label: "CSV",        sub: "One file per table" },
			{ id: "sql",    label: "SQL",        sub: "CREATE + INSERT statements" },
		]
		: [
			{ id: "json", label: "JSON", sub: "One object per row" },
			{ id: "csv",  label: "CSV",  sub: "One file per table" },
			{ id: "sql",  label: "SQL",  sub: "CREATE + INSERT statements" },
		];
	const fmtGrid = useKeyboardGrid({
		count: FORMATS.length,
		columns: 1,
		onActivate: (i) => {
			if (loadResult) setLoadResult(null);
			setFmt(FORMATS[i].id);
		},
		initial: Math.max(0, FORMATS.findIndex((f) => f.id === fmt)),
	});

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
					{FORMATS.map((f, i) => {
						const k = fmtGrid.getItemProps(i);
						return (
						<div
							key={f.id}
							onClick={() => {
								if (loadResult) setLoadResult(null);
								setFmt(f.id);
							}}
							onMouseEnter={k.onMouseEnter}
							className={`rl-fmt-row ${fmt === f.id ? "active" : ""} ${k.className}`}
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
						);
					})}
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
										<Fragment key={table}>
											<dt>{table.toUpperCase()}</dt>
											<dd>{count.toLocaleString()}</dd>
										</Fragment>
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
	const [achievement, setAchievement] = useState<string | null>(null);
	const showAchievement = (msg: string) => {
		setAchievement(msg);
		window.setTimeout(() => setAchievement(null), 2200);
	};

	const next = () => {
		const i = RL_STAGES.findIndex((s) => s.id === stage);
		if (i < 0) return;
		const cleared = RL_STAGES[i];
		showAchievement(`+${cleared.xp} XP · ${cleared.label} CLEARED`);
		if (i < RL_STAGES.length - 1) setStage(RL_STAGES[i + 1].id);
	};
	const stageMeta = RL_STAGES.find((s) => s.id === stage);

	useGlobalKeys({
		onBack: onBack,
		onTab: (dir) => {
			const i = RL_STAGES.findIndex((s) => s.id === stage);
			if (i < 0) return;
			// Wrap around: Tab on the last stage cycles to the first; Shift+Tab
			// on the first cycles to the last.
			const len = RL_STAGES.length;
			const target = (i + dir + len) % len;
			if (target !== i) setStage(RL_STAGES[target].id);
		},
		onStageNumber: (n) => {
			if (n >= 1 && n <= RL_STAGES.length) setStage(RL_STAGES[n - 1].id);
		},
		stageCount: RL_STAGES.length,
	});
	return (
		<PipelineProvider
			projectId={project?.id ?? null}
			projectName={project?.name ?? null}
			resumed={resumed}
		>
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
							← DUNGEONS
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
					[ STAGE {RL_STAGES.findIndex((s) => s.id === stage) + 1}/{RL_STAGES.length}{" "}
					· {stageMeta?.label} · {stageMeta?.sub.toUpperCase()} ]
				</div>
				<div className="rl-stage" key={stage}>
					{stage === "upload" && <RlUpload onNext={next} />}
					{stage === "extract" && <RlExtract onNext={next} />}
					{stage === "transform" && <RlTransform onNext={next} />}
					{stage === "export" && <RlExport onDone={onBack} />}
				</div>
				{achievement && <RlAchievement message={achievement} />}
			</div>
		</PipelineProvider>
	);
}
