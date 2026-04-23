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
import { RL_STAGES, type Project, type ResumedSession, type StageId } from "./data";
import { IArrow, ICheck, IDisk, IUpload, IX } from "./icons";
import { MascotDeploy, MascotLoad } from "./Sprites";
import { RlTopbar } from "./Topbar";

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
	preview: Record<string, unknown>;
};

type LoadResult = {
	ok: boolean;
	output_files: string[];
	rows_written: Record<string, number>;
	errors: string[];
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
		const tableNames = resumed.tables.length > 0
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

async function uploadToBackend(
	files: File[],
	projectId: string | null,
): Promise<UploadResult> {
	// If any file is a DB file, use pre-extract endpoint (single file)
	const dbFile = files.find((f) => isDbFile(f.name));
	if (dbFile) {
		const form = new FormData();
		form.append("file", dbFile);
		if (projectId) form.append("project_id", projectId);
		const res = await fetch("/api/pre-extract", { method: "POST", body: form });
		if (!res.ok) {
			const err = await res.json().catch(() => null);
			throw new Error(err?.detail || "Upload failed");
		}
		const data = await res.json();
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
		};
	}

	// Flat files — use /api/upload
	const form = new FormData();
	for (const f of files) form.append("files", f);
	if (projectId) form.append("project_id", projectId);
	const res = await fetch("/api/upload", { method: "POST", body: form });
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

function RlUpload({ onNext }: { onNext: () => void }) {
	const { staged, addStaged, removeStaged, clearStaged, projectId, setUploadResult } =
		usePipelineCtx();
	const inputRef = useRef<HTMLInputElement | null>(null);
	const [uploading, setUploading] = useState(false);
	const [dragOver, setDragOver] = useState(false);
	const [error, setError] = useState<string | null>(null);

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

	const handleUpload = async () => {
		if (staged.length === 0) return;
		setUploading(true);
		setError(null);
		try {
			const result = await uploadToBackend(
				staged.map((s) => s.file),
				projectId,
			);
			setUploadResult(result);
			onNext();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Upload failed");
		} finally {
			setUploading(false);
		}
	};

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
					<IUpload size={10} /> UPLOAD DATA FILES
				</div>
				<div className="panel-body">
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

					{staged.length > 0 && (
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
				<button
					className="btn btn-primary"
					disabled={staged.length === 0 || uploading}
					onClick={handleUpload}
				>
					{uploading ? "UPLOADING…" : "UPLOAD & EXTRACT"} <IArrow size={10} />
				</button>
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
			onClick={onClose}
		>
			<div
				style={{
					background: "var(--lg-bg)",
					border: `2px solid ${editing ? "var(--lg-coral)" : "var(--lg-amber)"}`,
					maxWidth: "90vw",
					maxHeight: "85vh",
					width: "100%",
					display: "flex",
					flexDirection: "column",
					overflow: "hidden",
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
								{displayRows.map((row, ri) => (
									<tr key={ri}>
										<td
											style={{
												fontFamily: "var(--lg-mono)",
												fontSize: 9,
												color: "var(--lg-ink-mute)",
											}}
										>
											{(page - 1) * 100 + ri + 1}
										</td>
										{data.columns.map((col) =>
											editing ? (
												<td key={col} style={{ padding: 0 }}>
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
													/>
												</td>
											) : (
												<td key={col}>
													{row[col] != null ? String(row[col]) : "—"}
												</td>
											),
										)}
									</tr>
								))}
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
					<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}>
						PAGE {page} / {totalPages}
						{data && (
							<>
								{" · "}SHOWING {(page - 1) * 100 + 1}–
								{Math.min(page * 100, data.total_rows)} OF{" "}
								{data.total_rows.toLocaleString()}
							</>
						)}
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
		</div>
	);
}

// ---------- extract ----------

function RlExtract({ onNext }: { onNext: () => void }) {
	const { uploadResult } = usePipelineCtx();
	const tables = uploadResult?.tables ?? [];
	const totalRows = tables.reduce((a, t) => a + t.rowCount, 0);
	const [previewTable, setPreviewTable] = useState<string | null>(null);

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
				<div className="panel-head">
					<IDisk size={10} /> EXTRACTED {tables.length} TABLE
					{tables.length === 1 ? "" : "S"}
				</div>
				<div className="panel-body">
					<div
						style={{
							display: "flex",
							justifyContent: "space-between",
							fontFamily: "var(--lg-pixel)",
							fontSize: 9,
							letterSpacing: "0.1em",
							color: "var(--lg-ink-dim)",
							marginBottom: 6,
						}}
					>
						<span>
							READ {tables.length} / {tables.length} TABLES
						</span>
						<span style={{ color: "var(--lg-amber)" }}>100%</span>
					</div>
					<div className="progress" style={{ marginBottom: 16 }}>
						<span style={{ width: "100%" }} />
					</div>
					<div
						style={{
							display: "grid",
							gridTemplateColumns: "repeat(2,1fr)",
							gap: 6,
						}}
					>
						{tables.map((t) => (
							<div
								key={t.name}
								className="rl-file-row"
								style={{ background: "var(--lg-bg-2)" }}
							>
								<ICheck size={10} />
								<div style={{ flex: 1, fontSize: 11 }}>
									{t.name.toUpperCase()}
								</div>
								<div
									style={{
										display: "flex",
										alignItems: "center",
										gap: 8,
										fontSize: 10,
										color: "var(--lg-ink-mute)",
									}}
								>
									<span>{t.rowCount.toLocaleString()} rows · {t.colCount} cols</span>
									<button
										className="btn btn-ghost"
										style={{ padding: "2px 8px", fontSize: 9 }}
										onClick={(e) => {
											e.stopPropagation();
											setPreviewTable(t.name);
										}}
									>
										PREVIEW
									</button>
								</div>
							</div>
						))}
					</div>
					{tables.length === 0 && (
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-mute)",
								padding: 20,
								textAlign: "center",
							}}
						>
							No tables extracted yet. Go back to Upload first.
						</div>
					)}
				</div>
			</div>
			<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">EXTRACTED</div>
					<div className="panel-body">
						<div
							className="pixel"
							style={{ fontSize: 24, color: "var(--lg-amber)" }}
						>
							{tables.length} TABLE{tables.length === 1 ? "" : "S"}
						</div>
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-dim)",
								marginTop: 4,
							}}
						>
							{totalRows.toLocaleString()} ROWS
						</div>
					</div>
				</div>
				<div className="panel">
					<div className="panel-head">SCHEMA INFO</div>
					<div className="panel-body">
						<dl className="kv">
							<dt>TABLES</dt>
							<dd>{tables.length}</dd>
							<dt>COLUMNS</dt>
							<dd>
								{tables.reduce((a, t) => a + t.colCount, 0)}
							</dd>
							<dt>SESSION</dt>
							<dd
								style={{
									fontSize: 9,
									wordBreak: "break-all",
								}}
							>
								{uploadResult?.sessionId?.slice(0, 8) ?? "—"}
							</dd>
						</dl>
					</div>
				</div>
				<button
					className="btn btn-primary"
					onClick={onNext}
					disabled={tables.length === 0}
				>
					CONTINUE TO SELECT <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- select ----------

function RlSelect({ onNext }: { onNext: () => void }) {
	const { uploadResult } = usePipelineCtx();
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const tables = uploadResult?.tables ?? [];
	const schema = uploadResult?.schema ?? {};

	const rows = useMemo(() => {
		return tables.map((t) => {
			const colTypes = Object.values(schema[t.name] ?? {}) as string[];
			const uniqueTypes = Array.from(new Set(colTypes.map((v) =>
				typeof v === "string" ? v.toUpperCase() : "TEXT"
			)));
			return {
				n: t.name,
				r: t.rowCount,
				c: t.colCount,
				types: uniqueTypes.length > 0 ? uniqueTypes.slice(0, 4) : ["TEXT"],
				picked: true,
			};
		});
	}, [tables, schema]);

	const [picked, setPicked] = useState<boolean[]>(() => rows.map((r) => r.picked));

	useEffect(() => {
		setPicked((prev) =>
			prev.length === rows.length ? prev : rows.map((r) => r.picked),
		);
	}, [rows]);

	const safePicked =
		picked.length === rows.length ? picked : rows.map((r) => r.picked);
	const n = safePicked.filter(Boolean).length;
	const totalRows = rows.reduce(
		(a, t, i) => a + (safePicked[i] ? t.r : 0),
		0,
	);

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
					SELECT TABLES · {n} / {rows.length} PICKED
				</div>
				<div className="panel-body" style={{ padding: 0 }}>
					<table className="table">
						<thead>
							<tr>
								<th style={{ width: 30 }}></th>
								<th>TABLE</th>
								<th>ROWS</th>
								<th>COLS</th>
								<th>TYPES</th>
							</tr>
						</thead>
						<tbody>
							{rows.map((t, i) => (
								<tr
									key={t.n + i}
									onClick={() =>
										setPicked((p) => {
											const base =
												p.length === rows.length
													? p
													: rows.map((r) => r.picked);
											return base.map((v, j) => (j === i ? !v : v));
										})
									}
									style={{ cursor: "pointer" }}
									className={safePicked[i] ? "row-selected" : ""}
								>
									<td>
										<div
											style={{
												width: 12,
												height: 12,
												border: "1px solid var(--lg-amber)",
												background: safePicked[i]
													? "var(--lg-amber)"
													: "transparent",
												display: "flex",
												alignItems: "center",
												justifyContent: "center",
												color: "#1a1006",
											}}
										>
											{safePicked[i] && <ICheck size={8} />}
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
									<td style={{ fontVariantNumeric: "tabular-nums" }}>
										{t.r.toLocaleString()}
									</td>
									<td>{t.c}</td>
									<td>
										<div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
											{t.types.map((tp) => (
												<span key={tp} className="badge badge-mute">
													{tp}
												</span>
											))}
										</div>
									</td>
								</tr>
							))}
						</tbody>
					</table>
					{rows.length === 0 && (
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-mute)",
								padding: 20,
								textAlign: "center",
							}}
						>
							No tables to select. Upload files first.
						</div>
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
							{String(n).padStart(2, "0")} TBLS
						</div>
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-dim)",
								marginTop: 4,
							}}
						>
							{totalRows.toLocaleString()} ROWS
						</div>
					</div>
				</div>
				<div className="panel">
					<div className="panel-head">TIP</div>
					<div
						className="panel-body mono"
						style={{
							fontSize: 11,
							color: "var(--lg-ink-dim)",
							lineHeight: 1.7,
						}}
					>
						Unchecked tables are skipped at transform. You can come back and add
						more later.
					</div>
				</div>
				{error && (
					<div
						className="mono"
						style={{ fontSize: 11, color: "var(--lg-coral)" }}
					>
						{"> "}{error}
					</div>
				)}
				<button
					className="btn btn-primary"
					onClick={async () => {
						if (!uploadResult?.sessionId) return;
						const selectedNames = rows
							.filter((_, i) => safePicked[i])
							.map((r) => r.n);
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
							onNext();
						} catch (e) {
							setError(e instanceof Error ? e.message : "Selection failed");
						} finally {
							setSaving(false);
						}
					}}
					disabled={n === 0 || saving}
				>
					{saving ? "SAVING…" : "CONTINUE TO TRANSFORM"} <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

type ColOp = "keep" | "rename" | "cast" | "drop" | "add" | "fk";
type ColTransform = {
	op: string;
	params: Record<string, unknown>;
};
type ColEdit = {
	name: string;
	type: string;
	op: ColOp;
	targetName: string;
	targetType: string;
	isNew?: boolean;
	nullable?: boolean;
	defaultValue?: string;
	fkSourceTable?: string;
	fkSourceColumn?: string;
	fkMatchColumn?: string;
	fkLocalColumn?: string;
	transforms?: ColTransform[];
};

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
];

function resolveType(colInfo: unknown): string {
	if (typeof colInfo === "object" && colInfo) {
		const ci = colInfo as Record<string, unknown>;
		return String(ci.inferred_type ?? ci.original_type ?? "string");
	}
	return String(colInfo ?? "string");
}

function RlTransform({ onNext }: { onNext: () => void }) {
	const { uploadResult, setTransformResult } = usePipelineCtx();
	const [running, setRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const [result, setResult] = useState<TransformResult | null>(null);
	const tables = uploadResult?.tables ?? [];
	const preview = uploadResult?.preview ?? {};
	const schema = uploadResult?.schema ?? {};

	const [activeTable, setActiveTable] = useState<string>(tables[0]?.name ?? "");
	const [sel, setSel] = useState(0);
	const [renamingTable, setRenamingTable] = useState<string | null>(null);
	const [tableNames, setTableNames] = useState<Record<string, string>>(() =>
		Object.fromEntries(tables.map((t) => [t.name, t.name])),
	);

	// Per-table column edits state: { [tableName]: ColEdit[] }
	const [allEdits, setAllEdits] = useState<Record<string, ColEdit[]>>(() => {
		const init: Record<string, ColEdit[]> = {};
		for (const t of tables) {
			const tSchema = schema[t.name] ?? {};
			init[t.name] = Object.keys(tSchema).map((col) => ({
				name: col,
				type: resolveType(tSchema[col]),
				op: "keep" as ColOp,
				targetName: col.toLowerCase(),
				targetType: resolveType(tSchema[col]),
			}));
		}
		return init;
	});

	const cols = allEdits[activeTable] ?? [];
	const c = cols[sel] ?? cols[0];

	const updateCol = (idx: number, patch: Partial<ColEdit>) => {
		setAllEdits((prev) => {
			const tableCols = [...(prev[activeTable] ?? [])];
			tableCols[idx] = { ...tableCols[idx], ...patch };
			return { ...prev, [activeTable]: tableCols };
		});
	};

	const setOp = (idx: number, op: ColOp) => {
		const col = cols[idx];
		const patch: Partial<ColEdit> = { op };
		if (op === "keep") {
			patch.targetName = col.name.toLowerCase();
			patch.targetType = col.type;
		}
		if (op === "rename") {
			patch.targetType = col.type;
		}
		if (op === "cast") {
			patch.targetName = col.targetName || col.name.toLowerCase();
		}
		updateCol(idx, patch);
	};

	const addNewColumn = () => {
		const id = `__new_${Date.now()}`;
		const col: ColEdit = {
			name: id,
			type: "string",
			op: "add",
			targetName: "",
			targetType: "string",
			isNew: true,
			nullable: true,
			defaultValue: "",
		};
		setAllEdits((prev) => ({
			...prev,
			[activeTable]: [...(prev[activeTable] ?? []), col],
		}));
		setSel(cols.length);
	};

	const addFkColumn = () => {
		const id = `__fk_${Date.now()}`;
		const col: ColEdit = {
			name: id,
			type: "string",
			op: "fk",
			targetName: "",
			targetType: "string",
			isNew: true,
			fkSourceTable: tables.find((t) => t.name !== activeTable)?.name ?? "",
			fkSourceColumn: "",
			fkMatchColumn: "",
			fkLocalColumn: "",
		};
		setAllEdits((prev) => ({
			...prev,
			[activeTable]: [...(prev[activeTable] ?? []), col],
		}));
		setSel(cols.length);
	};

	const removeCol = (idx: number) => {
		setAllEdits((prev) => {
			const tableCols = [...(prev[activeTable] ?? [])];
			tableCols.splice(idx, 1);
			return { ...prev, [activeTable]: tableCols };
		});
		setSel((s) => Math.max(0, Math.min(s, cols.length - 2)));
	};

	const addTransform = (op: string) => {
		setAllEdits((prev) => {
			const tableCols = [...(prev[activeTable] ?? [])];
			const col = { ...tableCols[sel] };
			const transforms = [...(col.transforms ?? [])];
			transforms.push({ op, params: {} });
			col.transforms = transforms;
			tableCols[sel] = col;
			return { ...prev, [activeTable]: tableCols };
		});
	};

	const updateTransformParam = (tIdx: number, key: string, value: unknown) => {
		setAllEdits((prev) => {
			const tableCols = [...(prev[activeTable] ?? [])];
			const col = { ...tableCols[sel] };
			const transforms = [...(col.transforms ?? [])];
			transforms[tIdx] = {
				...transforms[tIdx],
				params: { ...transforms[tIdx].params, [key]: value },
			};
			col.transforms = transforms;
			tableCols[sel] = col;
			return { ...prev, [activeTable]: tableCols };
		});
	};

	const removeTransform = (tIdx: number) => {
		setAllEdits((prev) => {
			const tableCols = [...(prev[activeTable] ?? [])];
			const col = { ...tableCols[sel] };
			const transforms = [...(col.transforms ?? [])];
			transforms.splice(tIdx, 1);
			col.transforms = transforms;
			tableCols[sel] = col;
			return { ...prev, [activeTable]: tableCols };
		});
	};

	const activePreview = (preview[activeTable] ?? []) as Record<string, unknown>[];
	const kept = cols.filter((c) => c.op !== "drop");
	const tableRenameCount = Object.entries(tableNames).filter(([k, v]) => k !== v && v.trim() !== "").length;
	const transformCount = cols.reduce((n, c) => n + (c.transforms?.length ?? 0), 0);
	const opCounts = {
		rename: cols.filter((c) => c.op === "rename").length,
		cast: cols.filter((c) => c.op === "cast").length,
		drop: cols.filter((c) => c.op === "drop").length,
		add: cols.filter((c) => c.op === "add").length,
		fk: cols.filter((c) => c.op === "fk").length,
		tableRename: tableRenameCount,
		transforms: transformCount,
	};

	const serializeTransforms = (transforms?: ColTransform[]) => {
		if (!transforms || transforms.length === 0) return [];
		return transforms.map((tr) => {
			const params: Record<string, unknown> = {};
			for (const [k, v] of Object.entries(tr.params)) {
				if (k === "mapping" && typeof v === "string") {
					// Parse "key=value" lines into { key: value } dict
					const mapping: Record<string, string> = {};
					for (const line of v.split("\n")) {
						const trimmed = line.trim();
						if (!trimmed) continue;
						const eq = trimmed.indexOf("=");
						if (eq > 0) mapping[trimmed.slice(0, eq).trim()] = trimmed.slice(eq + 1).trim();
					}
					params[k] = mapping;
				} else if (k === "rules" && typeof v === "string") {
					// Parse "when=then" lines into [{when, then}] array
					const rules: { when: string; then: string }[] = [];
					for (const line of v.split("\n")) {
						const trimmed = line.trim();
						if (!trimmed) continue;
						const eq = trimmed.indexOf("=");
						if (eq > 0) rules.push({ when: trimmed.slice(0, eq).trim(), then: trimmed.slice(eq + 1).trim() });
					}
					params[k] = rules;
				} else {
					params[k] = v;
				}
			}
			return { op: tr.op, params };
		});
	};

	const saveAndTransform = async () => {
		if (!uploadResult?.sessionId) return;
		setRunning(true);
		setError(null);
		try {
			// 1. Save configuration
			const tableConfigs = tables.map((t) => {
				const edits = allEdits[t.name] ?? [];
				return {
					source_table: t.name,
					target_table: tableNames[t.name] || t.name,
					columns: edits.map((e) => {
						if (e.op === "add") {
							return {
								name: e.name,
								target_name: e.targetName,
								data_type: e.targetType,
								nullable: e.nullable ?? true,
								default_value: !e.nullable ? (e.defaultValue ?? null) : null,
								include: true,
								is_new: true,
								transforms: serializeTransforms(e.transforms),
							};
						}
						if (e.op === "fk") {
							return {
								name: e.name,
								target_name: e.targetName,
								data_type: e.targetType,
								nullable: true,
								include: true,
								is_new: true,
								fk_source_table: e.fkSourceTable,
								fk_source_column: e.fkSourceColumn,
								fk_match_column: e.fkMatchColumn,
								fk_local_column: e.fkLocalColumn,
								transforms: serializeTransforms(e.transforms),
							};
						}
						return {
							name: e.name,
							target_name: e.op === "rename" || e.op === "cast" ? e.targetName : undefined,
							data_type: e.op === "cast" ? e.targetType : e.type,
							nullable: true,
							include: e.op !== "drop",
							transforms: serializeTransforms(e.transforms),
						};
					}),
				};
			});
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

			// 2. Run transform
			const res = await fetch(`/api/transform/${uploadResult.sessionId}`);
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || "Transform failed");
			}
			const data = await res.json();
			setResult(data);
			setTransformResult(data);
		} catch (e) {
			setError(e instanceof Error ? e.message : "Transform failed");
		} finally {
			setRunning(false);
		}
	};

	return (
		<div
			style={{
				marginTop: 14,
				display: "flex",
				flexDirection: "column",
				gap: 14,
			}}
		>
			{/* Table tabs + summary */}
			<div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
				{tables.map((t) => (
					<div key={t.name} style={{ display: "flex", alignItems: "center", gap: 2 }}>
						{renamingTable === t.name ? (
							<div style={{ display: "flex", alignItems: "center", gap: 4 }}>
								<input
									className="input"
									style={{ width: 120, padding: "4px 8px", fontSize: 10 }}
									value={tableNames[t.name] ?? t.name}
									onChange={(e) =>
										setTableNames((prev) => ({ ...prev, [t.name]: e.target.value }))
									}
									onKeyDown={(e) => {
										if (e.key === "Enter") setRenamingTable(null);
										if (e.key === "Escape") {
											setTableNames((prev) => ({ ...prev, [t.name]: t.name }));
											setRenamingTable(null);
										}
									}}
									autoFocus
								/>
								<button
									className="btn btn-ghost"
									style={{ padding: "4px 6px", fontSize: 9 }}
									onClick={() => setRenamingTable(null)}
								>
									<ICheck size={8} />
								</button>
							</div>
						) : (
							<>
								<button
									className={`btn ${t.name === activeTable ? "btn-primary" : "btn-ghost"}`}
									style={{ padding: "6px 12px", fontSize: 10 }}
									onClick={() => {
										setActiveTable(t.name);
										setSel(0);
									}}
								>
									{tableNames[t.name] !== t.name ? (
										<>
											<span style={{ textDecoration: "line-through", opacity: 0.5, marginRight: 4 }}>
												{t.name.toUpperCase()}
											</span>
											{(tableNames[t.name] ?? t.name).toUpperCase()}
										</>
									) : (
										t.name.toUpperCase()
									)}
								</button>
								<button
									className="btn btn-ghost"
									style={{ padding: "2px 4px", fontSize: 8, opacity: 0.6 }}
									onClick={() => setRenamingTable(t.name)}
									title="Rename table"
								>
									✎
								</button>
							</>
						)}
					</div>
				))}
				<div style={{ flex: 1 }} />
				<div
					className="panel"
					style={{
						padding: "6px 14px",
						display: "flex",
						alignItems: "center",
						gap: 12,
					}}
				>
					<span
						className="pixel"
						style={{ fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.1em" }}
					>
						OPS
					</span>
					<span
						className="pixel"
						style={{ fontSize: 12, color: "var(--lg-amber)" }}
					>
						{opCounts.rename + opCounts.cast + opCounts.drop + opCounts.add + opCounts.fk + opCounts.tableRename + opCounts.transforms}
					</span>
					<span className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
						{opCounts.rename} rename · {opCounts.cast} cast · {opCounts.drop} drop{opCounts.add > 0 ? ` · ${opCounts.add} new` : ""}{opCounts.fk > 0 ? ` · ${opCounts.fk} fk` : ""}{opCounts.tableRename > 0 ? ` · ${opCounts.tableRename} tbl rename` : ""}{opCounts.transforms > 0 ? ` · ${opCounts.transforms} transforms` : ""}
					</span>
				</div>
			</div>

			{/* Column list + edit panel */}
			<div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
				<div className="panel">
					<div className="panel-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
						<span>COLUMN EDITS — {activeTable.toUpperCase()}</span>
						<div style={{ display: "flex", gap: 4 }}>
							<button
								className="btn btn-ghost"
								style={{ padding: "3px 8px", fontSize: 9 }}
								onClick={addNewColumn}
							>
								+ COLUMN
							</button>
							<button
								className="btn btn-ghost"
								style={{ padding: "3px 8px", fontSize: 9 }}
								onClick={addFkColumn}
							>
								+ FK
							</button>
						</div>
					</div>
					<div className="panel-body" style={{ padding: 0 }}>
						{cols.length === 0 ? (
							<div
								className="mono"
								style={{ fontSize: 11, color: "var(--lg-ink-mute)", padding: 20, textAlign: "center" }}
							>
								No columns available.
							</div>
						) : (
							cols.map((col, i) => (
								<div
									key={col.name}
									className={`rl-col-row ${i === sel ? "row-selected" : ""} ${col.op === "drop" ? "dropped" : ""}`}
									onClick={() => setSel(i)}
									style={{ cursor: "pointer" }}
								>
									<div style={{ flex: 1.4 }}>
										{col.op === "add" || col.op === "fk" ? (
											<span
												style={{
													color: "var(--lg-amber)",
													fontFamily: "var(--lg-pixel)",
													fontSize: 9,
												}}
											>
												{col.targetName || "(unnamed)"}
											</span>
										) : col.op === "rename" || col.op === "cast" ? (
											<>
												<span
													style={{
														color: "var(--lg-ink-mute)",
														textDecoration: "line-through",
														marginRight: 6,
														fontSize: 10,
													}}
												>
													{col.name}
												</span>
												<span
													style={{
														color: "var(--lg-amber)",
														fontFamily: "var(--lg-pixel)",
														fontSize: 9,
													}}
												>
													{col.targetName}
												</span>
											</>
										) : (
											<span
												style={{
													color: col.op === "drop" ? "var(--lg-ink-mute)" : "var(--lg-ink)",
													fontFamily: "var(--lg-pixel)",
													fontSize: 9,
													textDecoration: col.op === "drop" ? "line-through" : "none",
												}}
											>
												{col.name}
											</span>
										)}
									</div>
									<div
										style={{
											flex: 1,
											fontFamily: "var(--lg-mono)",
											fontSize: 10,
											color: "var(--lg-ink-dim)",
										}}
									>
										{col.op === "cast" ? (
											<>
												<span style={{ textDecoration: "line-through", marginRight: 4 }}>
													{col.type.toUpperCase()}
												</span>
												<span style={{ color: "var(--lg-amber)" }}>
													{col.targetType.toUpperCase()}
												</span>
											</>
										) : col.op === "fk" ? (
											<span style={{ color: "var(--lg-ink-mute)", fontSize: 9 }}>
												{col.fkSourceTable ? `${col.fkSourceTable}.${col.fkSourceColumn || "?"}` : "—"}
											</span>
										) : (
											(col.op === "add" ? col.targetType : col.type).toUpperCase()
										)}
									</div>
									<div style={{ width: 80, textAlign: "right" }}>
										{col.op === "keep" && <span className="badge badge-mute">KEEP</span>}
										{col.op === "rename" && <span className="badge badge-ok">RENAME</span>}
										{col.op === "cast" && <span className="badge badge-warn">CAST</span>}
										{col.op === "drop" && <span className="badge badge-err">DROP</span>}
										{col.op === "add" && <span className="badge badge-solid">NEW</span>}
										{col.op === "fk" && <span className="badge badge-solid">FK</span>}
									</div>
								</div>
							))
						)}
					</div>
				</div>

				<div className="panel">
					<div className="panel-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
						<span>EDIT · {c ? (c.isNew ? (c.targetName || "(unnamed)") : c.name) : "—"}</span>
						{c?.isNew && (
							<button
								className="btn btn-ghost"
								style={{ padding: "2px 6px", fontSize: 9, color: "var(--lg-coral)" }}
								onClick={() => removeCol(sel)}
							>
								<IX size={8} /> REMOVE
							</button>
						)}
					</div>
					<div className="panel-body">
						{c && !c.isNew && (
							<>
								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									OPERATION
								</div>
								<div
									style={{
										display: "grid",
										gridTemplateColumns: "repeat(4,1fr)",
										gap: 4,
										marginBottom: 12,
									}}
								>
									{(["keep", "rename", "cast", "drop"] as const).map((k) => (
										<button
											key={k}
											className={`btn ${c.op === k ? "btn-primary" : "btn-ghost"}`}
											style={{ padding: "5px 6px", fontSize: 9, justifyContent: "center" }}
											onClick={() => setOp(sel, k)}
										>
											{k.toUpperCase()}
										</button>
									))}
								</div>

								{c.op === "rename" && (
									<>
										<div
											className="pixel"
											style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4 }}
										>
											NEW NAME
										</div>
										<input
											className="input"
											value={c.targetName}
											onChange={(e) => updateCol(sel, { targetName: e.target.value })}
										/>
									</>
								)}

								{c.op === "cast" && (
									<>
										<div
											className="pixel"
											style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4 }}
										>
											CAST TO
										</div>
										<div
											style={{
												display: "grid",
												gridTemplateColumns: "repeat(3,1fr)",
												gap: 3,
												marginBottom: 12,
												maxHeight: 180,
												overflowY: "auto",
											}}
										>
											{CAST_TYPES.map((tp) => (
												<button
													key={tp}
													className={`btn ${c.targetType === tp ? "btn-primary" : "btn-ghost"}`}
													style={{ padding: "4px 6px", fontSize: 8, justifyContent: "flex-start" }}
													onClick={() => updateCol(sel, { targetType: tp })}
												>
													{tp.toUpperCase()}
												</button>
											))}
										</div>
										<div
											className="pixel"
											style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4 }}
										>
											RENAME (OPTIONAL)
										</div>
										<input
											className="input"
											value={c.targetName}
											onChange={(e) => updateCol(sel, { targetName: e.target.value })}
										/>
									</>
								)}

								{c.op === "drop" && (
									<div
										style={{
											padding: 10,
											border: "1px solid var(--lg-coral)",
											color: "var(--lg-coral)",
											fontSize: 11,
										}}
									>
										Column will be removed. Source data is preserved.
									</div>
								)}

								{c.op === "keep" && (
									<div
										style={{
											padding: 10,
											border: "1px solid var(--lg-border)",
											color: "var(--lg-ink-dim)",
											fontSize: 11,
										}}
									>
										Pass-through · value and type preserved.
									</div>
								)}

								{/* Column transforms */}
								<div style={{ marginTop: 16, borderTop: "1px solid var(--lg-border)", paddingTop: 12 }}>
									<div className="pixel" style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 6, letterSpacing: "0.1em" }}>
										TRANSFORMS {c.transforms?.length ? `(${c.transforms.length})` : ""}
									</div>
									{(c.transforms ?? []).map((t, tIdx) => {
										const opMeta = TRANSFORM_OPS.find((o) => o.id === t.op);
										return (
											<div key={tIdx} style={{ marginBottom: 10, padding: 8, border: "1px solid var(--lg-border)", background: "var(--lg-bg-2)" }}>
												<div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
													<span className="pixel" style={{ fontSize: 8, color: "var(--lg-amber)", letterSpacing: "0.1em" }}>
														{tIdx + 1}. {opMeta?.label ?? t.op.toUpperCase()}
													</span>
													<button className="link" style={{ fontSize: 8, color: "var(--lg-coral)" }} onClick={() => removeTransform(tIdx)}>
														<IX size={7} />
													</button>
												</div>
												{opMeta?.params.map((p) => (
													<div key={p.key} style={{ marginBottom: 6 }}>
														<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", marginBottom: 2 }}>{p.label}</div>
														{p.type === "text" && (
															<input className="input" style={{ fontSize: 10, padding: "3px 6px" }} placeholder={p.placeholder ?? ""} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)} />
														)}
														{p.type === "select" && (
															<select className="input" style={{ fontSize: 10, padding: "3px 6px" }} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)}>
																<option value="">—</option>
																{p.options?.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
															</select>
														)}
														{p.type === "checkbox" && (
															<label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, cursor: "pointer" }}>
																<input type="checkbox" checked={!!t.params[p.key]} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.checked)} />
																<span className="mono" style={{ color: "var(--lg-ink-dim)" }}>enabled</span>
															</label>
														)}
														{p.type === "textarea" && (
															<textarea className="input" style={{ fontSize: 10, padding: "3px 6px", minHeight: 50, resize: "vertical", fontFamily: "var(--lg-mono)" }} placeholder={p.key === "mapping" ? "ILS=NIS\nUSD=USD" : p.key === "rules" ? "posted=delivered\ndraft=draft" : ""} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)} />
														)}
													</div>
												))}
											</div>
										);
									})}
									<select className="input" style={{ fontSize: 10, padding: "4px 6px", color: "var(--lg-ink-dim)" }} value="" onChange={(e) => { if (e.target.value) addTransform(e.target.value); e.target.value = ""; }}>
										<option value="">+ ADD TRANSFORM…</option>
										{TRANSFORM_OPS.map((o) => (<option key={o.id} value={o.id}>{o.label}</option>))}
									</select>
								</div>
							</>
						)}

						{c?.op === "add" && (
							<>
								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									COLUMN NAME
								</div>
								<input
									className="input"
									style={{ marginBottom: 12 }}
									value={c.targetName}
									placeholder="new_column"
									onChange={(e) => updateCol(sel, { targetName: e.target.value })}
								/>

								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									DATA TYPE
								</div>
								<div
									style={{
										display: "grid",
										gridTemplateColumns: "repeat(3,1fr)",
										gap: 3,
										marginBottom: 12,
										maxHeight: 180,
										overflowY: "auto",
									}}
								>
									{CAST_TYPES.map((tp) => (
										<button
											key={tp}
											className={`btn ${c.targetType === tp ? "btn-primary" : "btn-ghost"}`}
											style={{ padding: "4px 6px", fontSize: 8, justifyContent: "flex-start" }}
											onClick={() => updateCol(sel, { targetType: tp })}
										>
											{tp.toUpperCase()}
										</button>
									))}
								</div>

								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									NULLABLE
								</div>
								<div style={{ display: "flex", gap: 4, marginBottom: 12 }}>
									<button
										className={`btn ${c.nullable ? "btn-primary" : "btn-ghost"}`}
										style={{ padding: "5px 10px", fontSize: 9, flex: 1, justifyContent: "center" }}
										onClick={() => updateCol(sel, { nullable: true, defaultValue: "" })}
									>
										NULLABLE
									</button>
									<button
										className={`btn ${!c.nullable ? "btn-primary" : "btn-ghost"}`}
										style={{ padding: "5px 10px", fontSize: 9, flex: 1, justifyContent: "center" }}
										onClick={() => updateCol(sel, { nullable: false })}
									>
										NOT NULL
									</button>
								</div>

								{!c.nullable && (
									<>
										<div
											className="pixel"
											style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
										>
											DEFAULT VALUE
										</div>
										<input
											className="input"
											value={c.defaultValue ?? ""}
											placeholder="default value for all rows"
											onChange={(e) => updateCol(sel, { defaultValue: e.target.value })}
										/>
									</>
								)}

								{c.nullable && (
									<div
										style={{
											padding: 10,
											border: "1px solid var(--lg-border)",
											color: "var(--lg-ink-dim)",
											fontSize: 11,
										}}
									>
										All rows will have NULL for this column.
									</div>
								)}

								{/* Column transforms for new columns */}
								<div style={{ marginTop: 16, borderTop: "1px solid var(--lg-border)", paddingTop: 12 }}>
									<div className="pixel" style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 6, letterSpacing: "0.1em" }}>
										TRANSFORMS {c.transforms?.length ? `(${c.transforms.length})` : ""}
									</div>
									{(c.transforms ?? []).map((t, tIdx) => {
										const opMeta = TRANSFORM_OPS.find((o) => o.id === t.op);
										return (
											<div key={tIdx} style={{ marginBottom: 10, padding: 8, border: "1px solid var(--lg-border)", background: "var(--lg-bg-2)" }}>
												<div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
													<span className="pixel" style={{ fontSize: 8, color: "var(--lg-amber)", letterSpacing: "0.1em" }}>{tIdx + 1}. {opMeta?.label ?? t.op.toUpperCase()}</span>
													<button className="link" style={{ fontSize: 8, color: "var(--lg-coral)" }} onClick={() => removeTransform(tIdx)}><IX size={7} /></button>
												</div>
												{opMeta?.params.map((p) => (
													<div key={p.key} style={{ marginBottom: 6 }}>
														<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", marginBottom: 2 }}>{p.label}</div>
														{p.type === "text" && (<input className="input" style={{ fontSize: 10, padding: "3px 6px" }} placeholder={p.placeholder ?? ""} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)} />)}
														{p.type === "select" && (<select className="input" style={{ fontSize: 10, padding: "3px 6px" }} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)}><option value="">—</option>{p.options?.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}</select>)}
														{p.type === "checkbox" && (<label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, cursor: "pointer" }}><input type="checkbox" checked={!!t.params[p.key]} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.checked)} /><span className="mono" style={{ color: "var(--lg-ink-dim)" }}>enabled</span></label>)}
														{p.type === "textarea" && (<textarea className="input" style={{ fontSize: 10, padding: "3px 6px", minHeight: 50, resize: "vertical", fontFamily: "var(--lg-mono)" }} placeholder={p.key === "mapping" ? "ILS=NIS\nUSD=USD" : p.key === "rules" ? "posted=delivered\ndraft=draft" : ""} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)} />)}
													</div>
												))}
											</div>
										);
									})}
									<select className="input" style={{ fontSize: 10, padding: "4px 6px", color: "var(--lg-ink-dim)" }} value="" onChange={(e) => { if (e.target.value) addTransform(e.target.value); e.target.value = ""; }}>
										<option value="">+ ADD TRANSFORM…</option>
										{TRANSFORM_OPS.map((o) => (<option key={o.id} value={o.id}>{o.label}</option>))}
									</select>
								</div>
							</>
						)}

						{c?.op === "fk" && (
							<>
								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									COLUMN NAME
								</div>
								<input
									className="input"
									style={{ marginBottom: 12 }}
									value={c.targetName}
									placeholder="looked_up_column"
									onChange={(e) => updateCol(sel, { targetName: e.target.value })}
								/>

								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									DATA TYPE
								</div>
								<div
									style={{
										display: "grid",
										gridTemplateColumns: "repeat(3,1fr)",
										gap: 3,
										marginBottom: 12,
										maxHeight: 180,
										overflowY: "auto",
									}}
								>
									{CAST_TYPES.map((tp) => (
										<button
											key={tp}
											className={`btn ${c.targetType === tp ? "btn-primary" : "btn-ghost"}`}
											style={{ padding: "4px 6px", fontSize: 8, justifyContent: "flex-start" }}
											onClick={() => updateCol(sel, { targetType: tp })}
										>
											{tp.toUpperCase()}
										</button>
									))}
								</div>

								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									LOCAL COLUMN (FK)
								</div>
								<select
									className="input"
									style={{ marginBottom: 12 }}
									value={c.fkLocalColumn ?? ""}
									onChange={(e) => updateCol(sel, { fkLocalColumn: e.target.value })}
								>
									<option value="">— select column —</option>
									{cols.filter((x) => !x.isNew).map((x) => (
										<option key={x.name} value={x.name}>{x.name}</option>
									))}
								</select>

								<div
									className="pixel"
									style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
								>
									SOURCE TABLE
								</div>
								<select
									className="input"
									style={{ marginBottom: 12 }}
									value={c.fkSourceTable ?? ""}
									onChange={(e) => {
										updateCol(sel, {
											fkSourceTable: e.target.value,
											fkMatchColumn: "",
											fkSourceColumn: "",
										});
									}}
								>
									<option value="">— select table —</option>
									{tables.map((t) => (
										<option key={t.name} value={t.name}>{t.name}</option>
									))}
								</select>

								{c.fkSourceTable && (
									<>
										<div
											className="pixel"
											style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
										>
											MATCH COLUMN (in {c.fkSourceTable.toUpperCase()})
										</div>
										<select
											className="input"
											style={{ marginBottom: 12 }}
											value={c.fkMatchColumn ?? ""}
											onChange={(e) => updateCol(sel, { fkMatchColumn: e.target.value })}
										>
											<option value="">— select column —</option>
											{(tables.find((t) => t.name === c.fkSourceTable)?.columns ?? []).map((col) => (
												<option key={col} value={col}>{col}</option>
											))}
										</select>

										<div
											className="pixel"
											style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 4, letterSpacing: "0.1em" }}
										>
											VALUE COLUMN (pull from {c.fkSourceTable.toUpperCase()})
										</div>
										<select
											className="input"
											value={c.fkSourceColumn ?? ""}
											onChange={(e) => updateCol(sel, { fkSourceColumn: e.target.value })}
										>
											<option value="">— select column —</option>
											{(tables.find((t) => t.name === c.fkSourceTable)?.columns ?? []).map((col) => (
												<option key={col} value={col}>{col}</option>
											))}
										</select>
									</>
								)}

								{c.fkLocalColumn && c.fkSourceTable && c.fkMatchColumn && c.fkSourceColumn && (
									<div
										style={{
											marginTop: 12,
											padding: 10,
											border: "1px solid var(--lg-amber)",
											color: "var(--lg-ink-dim)",
											fontSize: 10,
											lineHeight: 1.6,
											fontFamily: "var(--lg-mono)",
										}}
									>
										{activeTable}.{c.fkLocalColumn} → {c.fkSourceTable}.{c.fkMatchColumn}
										<br />
										pull: {c.fkSourceTable}.{c.fkSourceColumn}
									</div>
								)}

								{/* Column transforms for FK columns */}
								<div style={{ marginTop: 16, borderTop: "1px solid var(--lg-border)", paddingTop: 12 }}>
									<div className="pixel" style={{ fontSize: 10, color: "var(--lg-ink-mute)", marginBottom: 6, letterSpacing: "0.1em" }}>
										TRANSFORMS {c.transforms?.length ? `(${c.transforms.length})` : ""}
									</div>
									{(c.transforms ?? []).map((t, tIdx) => {
										const opMeta = TRANSFORM_OPS.find((o) => o.id === t.op);
										return (
											<div key={tIdx} style={{ marginBottom: 10, padding: 8, border: "1px solid var(--lg-border)", background: "var(--lg-bg-2)" }}>
												<div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
													<span className="pixel" style={{ fontSize: 8, color: "var(--lg-amber)", letterSpacing: "0.1em" }}>{tIdx + 1}. {opMeta?.label ?? t.op.toUpperCase()}</span>
													<button className="link" style={{ fontSize: 8, color: "var(--lg-coral)" }} onClick={() => removeTransform(tIdx)}><IX size={7} /></button>
												</div>
												{opMeta?.params.map((p) => (
													<div key={p.key} style={{ marginBottom: 6 }}>
														<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", marginBottom: 2 }}>{p.label}</div>
														{p.type === "text" && (<input className="input" style={{ fontSize: 10, padding: "3px 6px" }} placeholder={p.placeholder ?? ""} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)} />)}
														{p.type === "select" && (<select className="input" style={{ fontSize: 10, padding: "3px 6px" }} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)}><option value="">—</option>{p.options?.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}</select>)}
														{p.type === "checkbox" && (<label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 10, cursor: "pointer" }}><input type="checkbox" checked={!!t.params[p.key]} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.checked)} /><span className="mono" style={{ color: "var(--lg-ink-dim)" }}>enabled</span></label>)}
														{p.type === "textarea" && (<textarea className="input" style={{ fontSize: 10, padding: "3px 6px", minHeight: 50, resize: "vertical", fontFamily: "var(--lg-mono)" }} placeholder={p.key === "mapping" ? "ILS=NIS\nUSD=USD" : p.key === "rules" ? "posted=delivered\ndraft=draft" : ""} value={String(t.params[p.key] ?? "")} onChange={(e) => updateTransformParam(tIdx, p.key, e.target.value)} />)}
													</div>
												))}
											</div>
										);
									})}
									<select className="input" style={{ fontSize: 10, padding: "4px 6px", color: "var(--lg-ink-dim)" }} value="" onChange={(e) => { if (e.target.value) addTransform(e.target.value); e.target.value = ""; }}>
										<option value="">+ ADD TRANSFORM…</option>
										{TRANSFORM_OPS.map((o) => (<option key={o.id} value={o.id}>{o.label}</option>))}
									</select>
								</div>
							</>
						)}
					</div>
				</div>
			</div>

			{/* Preview table (before → after) */}
			{activePreview.length > 0 && (
				<div className="panel">
					<div className="panel-head">
						BEFORE / AFTER · {activeTable.toUpperCase()} · {activePreview.length} SAMPLE ROWS
					</div>
					<div className="panel-body" style={{ padding: 0 }}>
						<div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
							<div style={{ borderRight: "1px solid var(--lg-border)" }}>
								<div
									className="pixel"
									style={{ fontSize: 9, color: "var(--lg-ink-mute)", padding: "8px 10px", letterSpacing: "0.1em" }}
								>
									SOURCE · {activeTable.toUpperCase()}
								</div>
								<div style={{ overflow: "auto" }}>
									<table className="table">
										<thead>
											<tr>
												{cols.map((cl) => (
													<th
														key={cl.name}
														className={
															cl.op === "drop" ? "col-drop"
																: cl.op === "rename" ? "col-rename"
																: cl.op === "cast" ? "col-cast" : ""
														}
													>
														{cl.name}
													</th>
												))}
											</tr>
										</thead>
										<tbody>
											{activePreview.slice(0, 4).map((row, ri) => (
												<tr key={ri}>
													{cols.map((cl) => (
														<td
															key={cl.name}
															className={
																cl.op === "drop" ? "col-drop"
																	: cl.op === "rename" ? "col-rename"
																	: cl.op === "cast" ? "col-cast" : ""
															}
														>
															{row[cl.name] != null ? String(row[cl.name]) : "—"}
														</td>
													))}
												</tr>
											))}
										</tbody>
									</table>
								</div>
							</div>
							<div>
								<div
									className="pixel"
									style={{ fontSize: 9, color: "var(--lg-amber)", padding: "8px 10px", letterSpacing: "0.1em" }}
								>
									→ OUTPUT · {(tableNames[activeTable] || activeTable).toLowerCase()}
								</div>
								<div style={{ overflow: "auto" }}>
									<table className="table">
										<thead>
											<tr>
												{kept.map((cl) => (
													<th
														key={cl.name}
														className={
															cl.op === "cast" ? "col-cast"
																: cl.op === "rename" ? "col-rename" : ""
														}
													>
														{cl.targetName || "(unnamed)"}
														<div
															style={{
																fontFamily: "var(--lg-mono)",
																fontSize: 9,
																color: "var(--lg-ink-mute)",
																fontWeight: 400,
																letterSpacing: 0,
															}}
														>
															{(cl.op === "cast" || cl.op === "add" || cl.op === "fk" ? cl.targetType : cl.type).toUpperCase()}
															{cl.op === "fk" && " (FK)"}
														</div>
													</th>
												))}
											</tr>
										</thead>
										<tbody>
											{activePreview.slice(0, 4).map((row, ri) => (
												<tr key={ri}>
													{kept.map((cl) => (
														<td
															key={cl.name}
															className={
																cl.op === "cast" ? "col-cast"
																	: cl.op === "rename" ? "col-rename" : ""
															}
														>
															{cl.op === "add"
																? (cl.nullable ? <span style={{ color: "var(--lg-ink-mute)" }}>NULL</span> : (cl.defaultValue || "—"))
																: cl.op === "fk"
																	? <span style={{ color: "var(--lg-ink-mute)", fontStyle: "italic" }}>fk lookup</span>
																	: (row[cl.name] != null ? String(row[cl.name]) : "—")}
														</td>
													))}
												</tr>
											))}
										</tbody>
									</table>
								</div>
							</div>
						</div>
					</div>
				</div>
			)}

			{/* Transform result stats */}
			{result && (
				<div className="panel">
					<div className="panel-head">TRANSFORM RESULT</div>
					<div className="panel-body" style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
						<dl className="kv">
							<dt>TABLES</dt>
							<dd>{result.tables_transformed}</dd>
							<dt>ROWS</dt>
							<dd>{result.total_rows.toLocaleString()}</dd>
							<dt>ENCODING FIXES</dt>
							<dd>{result.encoding_conversions}</dd>
							<dt>TYPE CONVERSIONS</dt>
							<dd>{result.type_conversions}</dd>
							<dt>NULL NORMALIZATIONS</dt>
							<dd>{result.null_normalizations}</dd>
						</dl>
						{result.warnings.length > 0 && (
							<div>
								{result.warnings.map((w, i) => (
									<div key={i} className="mono" style={{ fontSize: 10, color: "var(--lg-coral)", marginTop: 4 }}>
										! {w}
									</div>
								))}
							</div>
						)}
					</div>
				</div>
			)}

			{error && (
				<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>
					{"> "}{error}
				</div>
			)}

			<div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
				{!result ? (
					<button
						className="btn btn-primary"
						onClick={saveAndTransform}
						disabled={running || !uploadResult?.sessionId}
					>
						{running ? "TRANSFORMING…" : "RUN TRANSFORM"} <IArrow size={10} />
					</button>
				) : (
					<button className="btn btn-primary" onClick={onNext}>
						CONTINUE TO MAP <IArrow size={10} />
					</button>
				)}
			</div>
		</div>
	);
}

// ---------- map (configure) ----------

type DDLColumn = {
	inferred_type: string;
	original_type: string;
	nullable: boolean;
};
type DDLSchema = Record<string, Record<string, DDLColumn>>;
type DDLEntry = {
	id: string;
	name: string;
	schema: DDLSchema;
	matchingTables: string[];
	uploadedAt: string;
};

function loadDDLTemplates(): DDLEntry[] {
	try {
		const raw = localStorage.getItem("retro-legacy.v2.ddl-templates");
		if (raw) return JSON.parse(raw) as DDLEntry[];
	} catch {}
	return [];
}

function RlMap({ onNext }: { onNext: () => void }) {
	const { uploadResult, transformResult } = usePipelineCtx();
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const tables = uploadResult?.tables ?? [];
	const schema = uploadResult?.schema ?? {};
	const transformPreview = (transformResult?.preview ?? {}) as Record<string, Record<string, unknown>[]>;

	const [activeTable, setActiveTable] = useState<string>(tables[0]?.name ?? "");
	const activeSchema = schema[activeTable] ?? {};
	const columns = Object.keys(activeSchema);
	const previewRows = (transformPreview[activeTable] ?? []) as Record<string, unknown>[];

	// DDL template support
	const [ddlTemplates] = useState<DDLEntry[]>(loadDDLTemplates);
	const [appliedDDL, setAppliedDDL] = useState<Record<string, DDLSchema[string]>>({});
	const [ddlPickerOpen, setDdlPickerOpen] = useState(false);

	const applyTemplate = (entry: DDLEntry, tableName: string) => {
		const ddlTable = entry.schema[tableName];
		if (ddlTable) {
			setAppliedDDL((prev) => ({ ...prev, [tableName]: ddlTable }));
		}
		setDdlPickerOpen(false);
	};

	const clearDDL = (tableName: string) => {
		setAppliedDDL((prev) => {
			const next = { ...prev };
			delete next[tableName];
			return next;
		});
	};

	// Find templates that have a matching table name
	const matchingTemplates = ddlTemplates.filter((e) =>
		Object.keys(e.schema).some((t) => t.toLowerCase() === activeTable.toLowerCase()),
	);

	const appliedCols = appliedDDL[activeTable];

	const getColumnType = (col: string): string => {
		if (appliedCols?.[col]) {
			return appliedCols[col].original_type;
		}
		const colInfo = activeSchema[col];
		if (typeof colInfo === "object" && colInfo) {
			return String((colInfo as Record<string, unknown>).inferred_type ?? (colInfo as Record<string, unknown>).original_type ?? "TEXT");
		}
		return String(colInfo ?? "TEXT");
	};

	const getColumnNullable = (col: string): boolean => {
		if (appliedCols?.[col]) {
			return appliedCols[col].nullable;
		}
		return true;
	};

	const saveConfig = async () => {
		if (!uploadResult?.sessionId) return;
		setSaving(true);
		setError(null);
		try {
			// If DDL was applied, upload it to backend session
			const appliedTables = Object.keys(appliedDDL);
			if (appliedTables.length > 0) {
				// Build DDL schema for backend
				const ddlPayload: Record<string, Record<string, DDLColumn>> = {};
				for (const [tbl, cols] of Object.entries(appliedDDL)) {
					ddlPayload[tbl] = cols;
				}

				// Use configure endpoint with DDL info embedded
				// First upload the DDL schema as a blob to the upload-ddl endpoint
				const ddlContent = appliedTables
					.map((tbl) => {
						const cols = appliedDDL[tbl];
						const colDefs = Object.entries(cols)
							.map(([name, col]) => `  "${name}" ${col.original_type}${col.nullable ? "" : " NOT NULL"}`)
							.join(",\n");
						return `CREATE TABLE "${tbl}" (\n${colDefs}\n);`;
					})
					.join("\n\n");

				const ddlBlob = new Blob([ddlContent], { type: "text/plain" });
				const ddlForm = new FormData();
				ddlForm.append("files", ddlBlob, "template.sql");
				const ddlRes = await fetch(`/api/upload-ddl/${uploadResult.sessionId}`, {
					method: "POST",
					body: ddlForm,
				});
				if (ddlRes.ok) {
					// Apply DDL to the tables
					await fetch(`/api/apply-ddl/${uploadResult.sessionId}`, {
						method: "POST",
						headers: { "Content-Type": "application/json" },
						body: JSON.stringify({ tables: appliedTables }),
					});
				}
			}

			// Fetch existing config to preserve transforms set in Transform stage
			let prevConfig: { tables?: { source_table: string; columns: { name: string; transforms?: { op: string; params: Record<string, unknown> }[] }[] }[] } = {};
			try {
				const cfgRes = await fetch(`/api/session/${uploadResult.sessionId}/config`);
				if (cfgRes.ok) prevConfig = await cfgRes.json();
			} catch { /* ignore */ }
			const prevTransforms: Record<string, Record<string, { op: string; params: Record<string, unknown> }[]>> = {};
			for (const tc of prevConfig.tables ?? []) {
				for (const cc of tc.columns ?? []) {
					if (cc.transforms && cc.transforms.length > 0) {
						if (!prevTransforms[tc.source_table]) prevTransforms[tc.source_table] = {};
						prevTransforms[tc.source_table][cc.name] = cc.transforms;
					}
				}
			}

			const tableConfigs = tables.map((t) => {
				const tSchema = schema[t.name] ?? {};
				const ddl = appliedDDL[t.name];
				const tblTransforms = prevTransforms[t.name] ?? {};
				const cols = Object.keys(tSchema).map((col) => ({
					name: col,
					data_type: ddl?.[col]
						? ddl[col].original_type
						: typeof tSchema[col] === "object"
							? String((tSchema[col] as Record<string, unknown>).inferred_type ?? "string")
							: String(tSchema[col] ?? "string"),
					nullable: ddl?.[col] ? ddl[col].nullable : true,
					include: true,
					transforms: tblTransforms[col] ?? [],
				}));
				return {
					source_table: t.name,
					columns: cols,
				};
			});
			const res = await fetch(
				`/api/configure/${uploadResult.sessionId}?phase=map`,
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ tables: tableConfigs }),
				},
			);
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || "Configuration failed");
			}
			onNext();
		} catch (e) {
			setError(e instanceof Error ? e.message : "Configuration failed");
		} finally {
			setSaving(false);
		}
	};

	return (
		<div
			style={{
				marginTop: 14,
				display: "flex",
				flexDirection: "column",
				gap: 14,
			}}
		>
			<div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
				{tables.map((t) => (
					<button
						key={t.name}
						className={`btn ${t.name === activeTable ? "btn-primary" : "btn-ghost"}`}
						style={{ padding: "6px 12px", fontSize: 10 }}
						onClick={() => setActiveTable(t.name)}
					>
						{t.name.toUpperCase()}
						{appliedDDL[t.name] && (
							<span className="badge badge-solid" style={{ marginLeft: 6, fontSize: 7 }}>DDL</span>
						)}
					</button>
				))}
				<div style={{ flex: 1 }} />
				<span className="badge badge-solid">
					<ICheck size={8} /> {tables.length} TABLE{tables.length === 1 ? "" : "S"} CONFIGURED
				</span>
			</div>

			<div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
				<div className="panel">
					<div className="panel-head" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
						<span>COLUMN MAPPING — {activeTable.toUpperCase()}</span>
						{appliedCols && (
							<span className="badge badge-solid" style={{ fontSize: 8 }}>DDL APPLIED</span>
						)}
					</div>
					<div className="panel-body" style={{ padding: 0 }}>
						{columns.length === 0 ? (
							<div
								className="mono"
								style={{ fontSize: 11, color: "var(--lg-ink-mute)", padding: 20, textAlign: "center" }}
							>
								No columns to configure.
							</div>
						) : (
							columns.map((col) => {
								const typeStr = getColumnType(col);
								const nullable = getColumnNullable(col);
								const hasDDLOverride = !!appliedCols?.[col];
								return (
									<div key={col} className="rl-col-row">
										<div style={{ flex: 1.4 }}>
											<span
												style={{
													color: "var(--lg-ink)",
													fontFamily: "var(--lg-pixel)",
													fontSize: 9,
												}}
											>
												{col}
											</span>
										</div>
										<div
											style={{
												flex: 0.8,
												fontFamily: "var(--lg-mono)",
												fontSize: 10,
												color: hasDDLOverride ? "var(--lg-amber)" : "var(--lg-ink-dim)",
											}}
										>
											{typeStr.toUpperCase()}
										</div>
										<div style={{ flex: 0.4, textAlign: "center" }}>
											<IArrow size={8} />
										</div>
										<div style={{ flex: 1.4 }}>
											<span
												style={{
													color: "var(--lg-amber)",
													fontFamily: "var(--lg-pixel)",
													fontSize: 9,
												}}
											>
												{col.toLowerCase()}
											</span>
										</div>
										<div style={{ width: 90, textAlign: "right", display: "flex", gap: 4, justifyContent: "flex-end" }}>
											<span className={`badge ${nullable ? "badge-mute" : "badge-warn"}`}>
												{nullable ? "NULL" : "NOT NULL"}
											</span>
										</div>
									</div>
								);
							})
						)}
					</div>
				</div>

				<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
					<div className="panel">
						<div className="panel-head">TABLE INFO</div>
						<div className="panel-body">
							<dl className="kv">
								<dt>SOURCE</dt>
								<dd>{activeTable.toUpperCase()}</dd>
								<dt>TARGET</dt>
								<dd>{activeTable.toLowerCase()}</dd>
								<dt>COLUMNS</dt>
								<dd>{columns.length}</dd>
								<dt>ROWS</dt>
								<dd>{(tables.find((t) => t.name === activeTable)?.rowCount ?? 0).toLocaleString()}</dd>
							</dl>
						</div>
					</div>

					{/* DDL Template section */}
					<div className="panel">
						<div className="panel-head">DDL TEMPLATE</div>
						<div className="panel-body">
							{appliedCols ? (
								<>
									<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", marginBottom: 8 }}>
										Schema overridden with DDL types and nullability constraints.
									</div>
									<button
										className="btn btn-ghost"
										style={{ padding: "4px 10px", fontSize: 10, color: "var(--lg-coral)" }}
										onClick={() => clearDDL(activeTable)}
									>
										<IX size={8} /> REMOVE DDL
									</button>
								</>
							) : ddlTemplates.length === 0 ? (
								<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-mute)", lineHeight: 1.6 }}>
									No DDL templates uploaded. Go to Templates to upload .SQL files with CREATE TABLE statements.
								</div>
							) : (
								<>
									<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", marginBottom: 8, lineHeight: 1.6 }}>
										Apply a DDL template to override column types and nullability for this table.
									</div>
									{ddlPickerOpen ? (
										<div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
											{ddlTemplates.map((entry) => {
												const ddlTableNames = Object.keys(entry.schema);
												const match = ddlTableNames.find(
													(t) => t.toLowerCase() === activeTable.toLowerCase(),
												);
												return (
													<div
														key={entry.id}
														className="rl-col-row"
														style={{ cursor: match ? "pointer" : "default", opacity: match ? 1 : 0.4 }}
														onClick={() => match && applyTemplate(entry, match)}
													>
														<div style={{ flex: 1 }}>
															<div
																className="pixel"
																style={{ fontSize: 9, color: "var(--lg-amber)" }}
															>
																{entry.name}
															</div>
															<div
																className="mono"
																style={{ fontSize: 9, color: "var(--lg-ink-mute)", marginTop: 2 }}
															>
																{ddlTableNames.length} tables · {match ? "MATCH" : "no match"}
															</div>
														</div>
														{match && (
															<span className="badge badge-ok" style={{ fontSize: 8 }}>APPLY</span>
														)}
													</div>
												);
											})}
											<button
												className="btn btn-ghost"
												style={{ padding: "4px 10px", fontSize: 10, marginTop: 4 }}
												onClick={() => setDdlPickerOpen(false)}
											>
												CANCEL
											</button>
										</div>
									) : (
										<button
											className="btn btn-ghost"
											style={{ padding: "5px 10px", fontSize: 10 }}
											onClick={() => setDdlPickerOpen(true)}
										>
											{matchingTemplates.length > 0
												? `APPLY TEMPLATE (${matchingTemplates.length} match)`
												: "BROWSE TEMPLATES"}
										</button>
									)}
								</>
							)}
						</div>
					</div>

					{transformResult && (
						<div className="panel">
							<div className="panel-head">TRANSFORM STATS</div>
							<div className="panel-body">
								<dl className="kv">
									<dt>ENCODING</dt>
									<dd>{transformResult.encoding_conversions} fixes</dd>
									<dt>TYPE CONV</dt>
									<dd>{transformResult.type_conversions}</dd>
									<dt>NULLS</dt>
									<dd>{transformResult.null_normalizations}</dd>
								</dl>
							</div>
						</div>
					)}
				</div>
			</div>

			{previewRows.length > 0 && (
				<div className="panel">
					<div className="panel-head">
						PREVIEW · {activeTable.toUpperCase()} · {previewRows.length} ROWS
					</div>
					<div className="panel-body" style={{ padding: 0, overflow: "auto" }}>
						<table className="table">
							<thead>
								<tr>
									{columns.map((col) => (
										<th key={col}>{col}</th>
									))}
								</tr>
							</thead>
							<tbody>
								{previewRows.slice(0, 5).map((row, ri) => (
									<tr key={ri}>
										{columns.map((col) => (
											<td key={col}>
												{row[col] != null ? String(row[col]) : "—"}
											</td>
										))}
									</tr>
								))}
							</tbody>
						</table>
					</div>
				</div>
			)}

			{error && (
				<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>
					{"> "}{error}
				</div>
			)}

			<div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
				<button
					className="btn btn-primary"
					onClick={saveConfig}
					disabled={saving || tables.length === 0}
				>
					{saving ? "SAVING…" : "CONTINUE TO EXPORT"} <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- export ----------

function RlExport({ onDone }: { onDone: () => void }) {
	const { projectId, uploadResult, transformResult, loadResult, setLoadResult } = usePipelineCtx();
	const [fmt, setFmt] = useState("json");
	const [running, setRunning] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const totalRows = transformResult?.total_rows ?? uploadResult?.tables.reduce((a, t) => a + t.rowCount, 0) ?? 0;

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
				body: JSON.stringify({ output_format: fmt }),
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
									color: fmt === f.id ? "#1a1006" : "var(--lg-amber)",
									letterSpacing: "0.1em",
								}}
							>
								{f.label}
							</div>
							<div
								className="mono"
								style={{
									fontSize: 10,
									color: fmt === f.id ? "#1a1006" : "var(--lg-ink-mute)",
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
				<div className="rl-mascot-slot">
					<MascotLoad size={150} />
				</div>
				<div className="panel">
					<div className="panel-head">
						{loadResult ? "COMPLETE" : "READY TO RUN"}
					</div>
					<div className="panel-body">
						<div
							className="pixel"
							style={{ fontSize: 22, color: "var(--lg-amber)" }}
						>
							{totalRows.toLocaleString()}
						</div>
						<div
							className="mono"
							style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}
						>
							{loadResult ? "ROWS EXPORTED" : "ROWS WILL EXPORT"}
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
					<div className="rl-run-cluster">
						<div className="rl-mascot-slot rl-mascot-slot-sm">
							<MascotDeploy size={130} />
						</div>
						<button
							className="btn btn-primary"
							onClick={runLoad}
							disabled={running || !uploadResult?.sessionId}
						>
							{running ? "EXPORTING…" : "▶ RUN PIPELINE"}
						</button>
					</div>
				) : (
					<button
						className="btn btn-primary"
						onClick={async () => {
							// Call stats to finalize the pipeline phase
							if (uploadResult?.sessionId) {
								try {
									await fetch(`/api/stats/${uploadResult.sessionId}`);
								} catch {
									// non-critical
								}
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
					{stage === "select" && <RlSelect onNext={next} />}
					{stage === "transform" && <RlTransform onNext={next} />}
					{stage === "map" && <RlMap onNext={next} />}
					{stage === "export" && <RlExport onDone={onBack} />}
				</div>
			</div>
		</PipelineProvider>
	);
}
