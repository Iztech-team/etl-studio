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
import { RL_STAGES, type Project, type StageId } from "./data";
import { IArrow, ICheck, IDisk, IDot, IUpload, IX } from "./icons";
import { RlTopbar } from "./Topbar";

// ---------- upload state ----------

type FileKind = "csv" | "tsv" | "json" | "sql" | "xlsx" | "ib" | "unknown";

export type UploadedTable = {
	id: string;
	name: string;
	displayName: string;
	size: number;
	kind: FileKind;
	columns: string[];
	rowCount: number | null;
	addedAt: number;
};

type PipelineCtx = {
	uploads: UploadedTable[];
	add: (tables: UploadedTable[]) => void;
	remove: (id: string) => void;
	clear: () => void;
};

const PipelineContext = createContext<PipelineCtx | null>(null);

function usePipelineCtx(): PipelineCtx {
	const ctx = useContext(PipelineContext);
	if (!ctx) throw new Error("PipelineContext not found");
	return ctx;
}

function PipelineProvider({ children }: { children: ReactNode }) {
	const [uploads, setUploads] = useState<UploadedTable[]>([]);
	const ctx: PipelineCtx = {
		uploads,
		add: (tables) => setUploads((prev) => [...prev, ...tables]),
		remove: (id) => setUploads((prev) => prev.filter((t) => t.id !== id)),
		clear: () => setUploads([]),
	};
	return (
		<PipelineContext.Provider value={ctx}>{children}</PipelineContext.Provider>
	);
}

const ACCEPT =
	".ib,.csv,.tsv,.json,.jsonl,.ndjson,.sql,.xlsx,.xls,text/csv,application/json,application/sql";

function detectKind(name: string): FileKind {
	const ext = name.toLowerCase().split(".").pop() ?? "";
	if (ext === "csv") return "csv";
	if (ext === "tsv") return "tsv";
	if (["json", "jsonl", "ndjson"].includes(ext)) return "json";
	if (ext === "sql") return "sql";
	if (["xlsx", "xls"].includes(ext)) return "xlsx";
	if (ext === "ib") return "ib";
	return "unknown";
}

function fmtSize(n: number): string {
	if (n < 1024) return n + " B";
	if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
	if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + " MB";
	return (n / (1024 * 1024 * 1024)).toFixed(1) + " GB";
}

function tableNameFromFile(name: string): string {
	return name
		.replace(/\.[^.]+$/, "")
		.replace(/[^a-zA-Z0-9_]+/g, "_")
		.toUpperCase();
}

async function parseDelimited(
	file: File,
	delim: string,
): Promise<{ columns: string[]; rowCount: number }> {
	const text = await file.text();
	const lines = text.split(/\r?\n/).filter((l) => l.length > 0);
	if (lines.length === 0) return { columns: [], rowCount: 0 };
	const columns = lines[0]
		.split(delim)
		.map((s) => s.trim().replace(/^"|"$/g, ""));
	return { columns, rowCount: Math.max(0, lines.length - 1) };
}

async function fileToTable(file: File): Promise<UploadedTable> {
	const kind = detectKind(file.name);
	let columns: string[] = [];
	let rowCount: number | null = null;
	try {
		if (kind === "csv") {
			const r = await parseDelimited(file, ",");
			columns = r.columns;
			rowCount = r.rowCount;
		} else if (kind === "tsv") {
			const r = await parseDelimited(file, "\t");
			columns = r.columns;
			rowCount = r.rowCount;
		} else if (kind === "json") {
			const text = await file.text();
			const nonEmpty = text.split(/\r?\n/).filter((l) => l.trim().length > 0);
			rowCount = nonEmpty.length;
		}
	} catch {
		// swallow parse errors — kind stays with empty columns
	}
	return {
		id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2, 8)}`,
		name: file.name,
		displayName: tableNameFromFile(file.name),
		size: file.size,
		kind,
		columns,
		rowCount,
		addedAt: Date.now(),
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
			: kind === "ib"
				? "badge badge-solid"
				: "badge badge-ok";
	return <span className={cls}>{label}</span>;
}

function RlUpload({ onNext }: { onNext: () => void }) {
	const { uploads, add, remove, clear } = usePipelineCtx();
	const inputRef = useRef<HTMLInputElement | null>(null);
	const [dragOver, setDragOver] = useState(false);
	const [busy, setBusy] = useState(false);

	const ingest = async (files: FileList | File[] | null) => {
		if (!files) return;
		const arr = Array.from(files);
		if (arr.length === 0) return;
		setBusy(true);
		try {
			const parsed = await Promise.all(arr.map(fileToTable));
			add(parsed);
		} finally {
			setBusy(false);
		}
	};

	const onInput = (e: ChangeEvent<HTMLInputElement>) => {
		void ingest(e.target.files);
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
		void ingest(e.dataTransfer?.files ?? null);
	};

	const totalRows = uploads.reduce((a, t) => a + (t.rowCount ?? 0), 0);

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
							.IB · .CSV · .TSV · .JSON · .SQL · .XLSX — EACH CSV IS ONE TABLE
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

					{busy && (
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-amber)",
								marginTop: 12,
							}}
						>
							PARSING FILES…
						</div>
					)}

					{uploads.length > 0 && (
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
								UPLOADED · {uploads.length} FILE{uploads.length === 1 ? "" : "S"} · {totalRows.toLocaleString()} ROW{totalRows === 1 ? "" : "S"}
							</div>
							<div
								style={{ display: "flex", flexDirection: "column", gap: 6 }}
							>
								{uploads.map((t) => (
									<div key={t.id} className="rl-file-row">
										<IDisk size={12} />
										<div style={{ flex: 1, minWidth: 0 }}>
											<div style={{ fontSize: 12 }}>{t.name}</div>
											<div
												style={{
													fontSize: 10,
													color: "var(--lg-ink-mute)",
													marginTop: 2,
												}}
											>
												{fmtSize(t.size)}
												{t.rowCount != null && (
													<>
														{" "}· {t.rowCount.toLocaleString()} ROWS
													</>
												)}
												{t.columns.length > 0 && (
													<>
														{" "}· {t.columns.length} COLS
													</>
												)}
											</div>
										</div>
										{kindBadge(t.kind)}
										<button
											className="link"
											style={{ fontSize: 10 }}
											onClick={() => remove(t.id)}
											title="Remove"
										>
											<IX size={8} /> REMOVE
										</button>
									</div>
								))}
							</div>
							{uploads.length > 1 && (
								<button
									className="btn btn-ghost"
									style={{ marginTop: 10, padding: "4px 10px", fontSize: 10 }}
									onClick={clear}
								>
									CLEAR ALL
								</button>
							)}
						</div>
					)}
				</div>
			</div>
			<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">CURRENT SOURCE</div>
					<div className="panel-body">
						{uploads.length === 0 ? (
							<>
								<div
									className="pixel"
									style={{ fontSize: 12, color: "var(--lg-amber)" }}
								>
									sales_archive.IB
								</div>
								<div
									className="mono"
									style={{
										fontSize: 11,
										color: "var(--lg-ink-dim)",
										marginTop: 6,
									}}
								>
									1.2 GB · 8 TABLES · 5.2M ROWS
								</div>
								<div
									className="mono"
									style={{
										fontSize: 10,
										color: "var(--lg-ink-mute)",
										marginTop: 10,
									}}
								>
									Upload your own files above to override this demo database.
								</div>
							</>
						) : (
							<>
								<div
									className="pixel"
									style={{ fontSize: 14, color: "var(--lg-amber)" }}
								>
									{uploads.length} TABLE{uploads.length === 1 ? "" : "S"}
								</div>
								<div
									className="mono"
									style={{
										fontSize: 11,
										color: "var(--lg-ink-dim)",
										marginTop: 6,
									}}
								>
									{totalRows.toLocaleString()} ROWS ·{" "}
									{fmtSize(uploads.reduce((a, t) => a + t.size, 0))}
								</div>
							</>
						)}
					</div>
				</div>
				<button className="btn btn-primary" onClick={onNext}>
					CONTINUE TO EXTRACT <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- extract ----------

const MOCK_EXTRACT: [string, number, string][] = [
	["CUSTOMERS", 48221, "6.2 MB"],
	["ORDERS", 892100, "84.1 MB"],
	["ORDER_LINES", 3120441, "210 MB"],
	["PRODUCTS", 12400, "1.8 MB"],
	["SUPPLIERS", 412, "120 KB"],
	["TERRITORIES", 54, "18 KB"],
	["PRICE_HIST", 204000, "14 MB"],
	["AUDIT_LOG", 980332, "22 MB"],
];

function RlExtract({ onNext }: { onNext: () => void }) {
	const { uploads } = usePipelineCtx();
	const hasUploads = uploads.length > 0;
	const totalRows = hasUploads
		? uploads.reduce((a, t) => a + (t.rowCount ?? 0), 0)
		: MOCK_EXTRACT.reduce((a, [, r]) => a + r, 0);
	const totalSize = hasUploads
		? fmtSize(uploads.reduce((a, t) => a + t.size, 0))
		: "338 MB CSV";

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
					<IDisk size={10} />{" "}
					{hasUploads
						? `PARSED ${uploads.length} UPLOAD${uploads.length === 1 ? "" : "S"}`
						: "EXTRACTING sales_archive.IB"}
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
							{hasUploads
								? `READ ${uploads.length} / ${uploads.length} FILES`
								: `PARSING RECORDS · 8 / 8 TABLES`}
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
						{hasUploads
							? uploads.map((t) => (
									<div
										key={t.id}
										className="rl-file-row"
										style={{ background: "var(--lg-bg-2)" }}
									>
										<ICheck size={10} />
										<div style={{ flex: 1, fontSize: 11 }}>{t.displayName}</div>
										<div
											style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}
										>
											{(t.rowCount ?? 0).toLocaleString()} · {fmtSize(t.size)}
										</div>
									</div>
								))
							: MOCK_EXTRACT.map(([n, r, s]) => (
									<div
										key={n}
										className="rl-file-row"
										style={{ background: "var(--lg-bg-2)" }}
									>
										<ICheck size={10} />
										<div style={{ flex: 1, fontSize: 11 }}>{n}</div>
										<div
											style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}
										>
											{r.toLocaleString()} · {s}
										</div>
									</div>
								))}
					</div>
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
							{hasUploads ? uploads.length : 8} TABLES
						</div>
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink-dim)",
								marginTop: 4,
							}}
						>
							{totalRows.toLocaleString()} ROWS · {totalSize}
						</div>
					</div>
				</div>
				<div className="panel">
					<div className="panel-head">
						{hasUploads ? "DETECTED" : "ENCODING DETECTED"}
					</div>
					<div className="panel-body">
						<dl className="kv">
							{hasUploads ? (
								<>
									<dt>TYPES</dt>
									<dd>
										{Array.from(new Set(uploads.map((t) => t.kind)))
											.map((k) => k.toUpperCase())
											.join(", ")}
									</dd>
									<dt>CHARSET</dt>
									<dd>UTF-8</dd>
								</>
							) : (
								<>
									<dt>FORMAT</dt>
									<dd>IB v4.2 (1997–2003)</dd>
									<dt>CHARSET</dt>
									<dd>CP1252</dd>
									<dt>ENDIAN</dt>
									<dd>little-endian</dd>
								</>
							)}
						</dl>
					</div>
				</div>
				<button className="btn btn-primary" onClick={onNext}>
					CONTINUE TO SELECT <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- select ----------

const MOCK_SELECT = [
	{ n: "CUSTOMERS", r: 48221, c: 14, s: "6.2 MB", types: ["INT", "VARCHAR", "DATE", "MONEY"], picked: true },
	{ n: "ORDERS", r: 892100, c: 22, s: "84.1 MB", types: ["INT", "VARCHAR", "DATE", "MONEY"], picked: true },
	{ n: "ORDER_LINES", r: 3120441, c: 11, s: "210 MB", types: ["INT", "DECIMAL", "MONEY"], picked: true },
	{ n: "PRODUCTS", r: 12400, c: 18, s: "1.8 MB", types: ["INT", "VARCHAR", "TEXT", "MONEY"], picked: true },
	{ n: "SUPPLIERS", r: 412, c: 9, s: "120 KB", types: ["INT", "VARCHAR"], picked: false },
	{ n: "TERRITORIES", r: 54, c: 6, s: "18 KB", types: ["INT", "VARCHAR"], picked: false },
	{ n: "PRICE_HIST", r: 204000, c: 7, s: "14 MB", types: ["INT", "MONEY", "DATE"], picked: false },
	{ n: "AUDIT_LOG", r: 980332, c: 5, s: "22 MB", types: ["INT", "VARCHAR", "DATE"], picked: false },
];

function RlSelect({ onNext }: { onNext: () => void }) {
	const { uploads } = usePipelineCtx();
	const rows = useMemo(() => {
		if (uploads.length === 0) return MOCK_SELECT;
		return uploads.map((t) => ({
			n: t.displayName,
			r: t.rowCount ?? 0,
			c: t.columns.length,
			s: fmtSize(t.size),
			types: [t.kind.toUpperCase()],
			picked: true,
		}));
	}, [uploads]);

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
								<th>SIZE</th>
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
										{t.n}
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
									<td style={{ color: "var(--lg-ink-dim)" }}>{t.s}</td>
								</tr>
							))}
						</tbody>
					</table>
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
				<button className="btn btn-primary" onClick={onNext}>
					CONTINUE TO TRANSFORM <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- transform (CUSTOMERS demo) ----------

type Col = {
	n: string;
	t: string;
	op: "keep" | "rename" | "cast" | "drop";
	to?: string;
	rename?: string;
};

const TRANSFORM_COLS: Col[] = [
	{ n: "CUST_ID", t: "INT", op: "rename", to: "customer_id" },
	{ n: "CUST_NAME_1", t: "VARCHAR(30)", op: "rename", to: "display_name" },
	{ n: "CUST_NAME_2", t: "VARCHAR(30)", op: "drop" },
	{ n: "ADDR_LINE", t: "VARCHAR(60)", op: "rename", to: "address_line_1" },
	{ n: "CITY", t: "VARCHAR(24)", op: "keep" },
	{ n: "STATE_CD", t: "CHAR(2)", op: "rename", to: "region" },
	{ n: "JOIN_DT", t: "DATE", op: "cast", to: "TIMESTAMPTZ", rename: "joined_at" },
	{ n: "CREDIT_LIM", t: "MONEY", op: "cast", to: "DECIMAL(12,2)", rename: "credit_limit" },
	{ n: "ACTV", t: "CHAR(1)", op: "cast", to: "BOOLEAN", rename: "is_active" },
];

const TRANSFORM_ROWS: string[][] = [
	["10045", "ACME NORTHWIND", "", "47 RAILROAD AVE", "PORTLAND", "OR", "1998-04-12", "5000.00", "Y"],
	["10046", "BOB'S TOOLS", "LLC", "12 MILL ST", "EUGENE", "OR", "1998-04-18", "2500.00", "Y"],
	["10047", "CEDAR CO.", "", "901 OAK DR", "SALEM", "OR", "1998-05-02", "10000.00", "N"],
	["10048", "DELTA FARMS", "", "7 RANCH RD", "BEND", "OR", "1998-05-11", "750.00", "Y"],
];

function RlTransform({ onNext }: { onNext: () => void }) {
	const COLS = TRANSFORM_COLS;
	const ROWS = TRANSFORM_ROWS;
	const [sel, setSel] = useState(1);
	const c = COLS[sel];

	const afterName = (c: Col) =>
		c.op === "cast"
			? c.rename || c.n.toLowerCase()
			: c.op === "rename"
				? c.to!
				: c.n.toLowerCase();
	const afterType = (c: Col) => (c.op === "cast" ? c.to! : c.t);
	const afterValue = (v: string, c: Col) => {
		if (c.op === "drop") return null;
		if (c.op === "cast") {
			if (c.to === "BOOLEAN") return v === "Y" ? "true" : "false";
			if (c.to === "TIMESTAMPTZ") return v + "T00:00:00Z";
			if (c.to?.startsWith("DECIMAL")) return Number(v).toFixed(2);
		}
		return v;
	};
	const kept = COLS.map((c, i) => ({ ...c, i })).filter((c) => c.op !== "drop");

	return (
		<div
			style={{
				marginTop: 14,
				display: "flex",
				flexDirection: "column",
				gap: 14,
			}}
		>
			<div style={{ display: "flex", gap: 6 }}>
				{["CUSTOMERS", "ORDERS", "ORDER_LINES", "PRODUCTS"].map((t) => (
					<button
						key={t}
						className={`btn ${t === "CUSTOMERS" ? "btn-primary" : "btn-ghost"}`}
						style={{ padding: "6px 12px", fontSize: 10 }}
					>
						{t}
					</button>
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
						style={{
							fontSize: 8,
							color: "var(--lg-ink-mute)",
							letterSpacing: "0.1em",
						}}
					>
						OPS
					</span>
					<span
						className="pixel"
						style={{ fontSize: 12, color: "var(--lg-amber)" }}
					>
						{COLS.filter((c) => c.op !== "keep").length + 1}
					</span>
					<span
						className="mono"
						style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}
					>
						{COLS.filter((c) => c.op === "rename" || c.op === "cast").length}{" "}
						rename · {COLS.filter((c) => c.op === "cast").length} cast ·{" "}
						{COLS.filter((c) => c.op === "drop").length} drop · 1 add
					</span>
				</div>
			</div>

			<div style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">COLUMN EDITS — CUSTOMERS</div>
					<div className="panel-body" style={{ padding: 0 }}>
						{COLS.map((col, i) => (
							<div
								key={col.n}
								className={`rl-col-row ${i === sel ? "row-selected" : ""} ${col.op === "drop" ? "dropped" : ""}`}
								onClick={() => setSel(i)}
							>
								<div style={{ flex: 1.4 }}>
									{col.op === "rename" || (col.op === "cast" && col.rename) ? (
										<>
											<span
												style={{
													color: "var(--lg-ink-mute)",
													textDecoration: "line-through",
													marginRight: 6,
													fontSize: 10,
												}}
											>
												{col.n}
											</span>
											<span
												style={{
													color: "var(--lg-amber)",
													fontFamily: "var(--lg-pixel)",
													fontSize: 9,
												}}
											>
												{col.to || col.rename}
											</span>
										</>
									) : (
										<span
											style={{
												color: "var(--lg-ink)",
												fontFamily: "var(--lg-pixel)",
												fontSize: 9,
											}}
										>
											{col.n}
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
											<span
												style={{
													textDecoration: "line-through",
													marginRight: 4,
												}}
											>
												{col.t}
											</span>
											<span style={{ color: "var(--lg-amber)" }}>{col.to}</span>
										</>
									) : (
										col.t
									)}
								</div>
								<div style={{ width: 80, textAlign: "right" }}>
									{col.op === "keep" && (
										<span className="badge badge-mute">KEEP</span>
									)}
									{col.op === "rename" && (
										<span className="badge badge-ok">RENAME</span>
									)}
									{col.op === "cast" && (
										<span className="badge badge-warn">CAST</span>
									)}
									{col.op === "drop" && (
										<span className="badge badge-err">DROP</span>
									)}
								</div>
							</div>
						))}
						<div
							className="rl-col-row"
							style={{
								borderTop: "2px dashed var(--lg-amber)",
								background: "rgba(255,179,71,0.04)",
							}}
						>
							<div
								style={{
									flex: 1.4,
									fontFamily: "var(--lg-pixel)",
									fontSize: 9,
									color: "var(--lg-amber)",
								}}
							>
								+ migrated_at
							</div>
							<div style={{ flex: 1, fontSize: 10, color: "var(--lg-amber)" }}>
								TIMESTAMPTZ · default NOW()
							</div>
							<div style={{ width: 80, textAlign: "right" }}>
								<span className="badge badge-solid">ADD</span>
							</div>
						</div>
					</div>
				</div>

				<div className="panel">
					<div className="panel-head">EDIT · {c.n}</div>
					<div className="panel-body">
						<div
							className="pixel"
							style={{
								fontSize: 10,
								color: "var(--lg-ink-mute)",
								marginBottom: 4,
								letterSpacing: "0.1em",
							}}
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
									style={{
										padding: "5px 6px",
										fontSize: 9,
										justifyContent: "center",
									}}
								>
									{k.toUpperCase()}
								</button>
							))}
						</div>
						{c.op === "rename" && (
							<>
								<div
									className="pixel"
									style={{
										fontSize: 10,
										color: "var(--lg-ink-mute)",
										marginBottom: 4,
									}}
								>
									NEW NAME
								</div>
								<input className="input" defaultValue={c.to} />
							</>
						)}
						{c.op === "cast" && (
							<>
								<div
									className="pixel"
									style={{
										fontSize: 10,
										color: "var(--lg-ink-mute)",
										marginBottom: 4,
									}}
								>
									CAST TO
								</div>
								<div
									style={{
										display: "grid",
										gridTemplateColumns: "repeat(2,1fr)",
										gap: 4,
										marginBottom: 12,
									}}
								>
									{[
										"TEXT",
										"INT",
										"BIGINT",
										"DECIMAL(12,2)",
										"BOOLEAN",
										"TIMESTAMPTZ",
									].map((tp) => (
										<button
											key={tp}
											className={`btn ${c.to === tp ? "btn-primary" : "btn-ghost"}`}
											style={{
												padding: "5px 8px",
												fontSize: 9,
												justifyContent: "flex-start",
											}}
										>
											{tp}
										</button>
									))}
								</div>
								<div
									className="pixel"
									style={{
										fontSize: 10,
										color: "var(--lg-ink-mute)",
										marginBottom: 4,
									}}
								>
									RENAME (OPTIONAL)
								</div>
								<input className="input" defaultValue={c.rename || ""} />
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
						<hr className="hr-pixel" />
						<div
							className="pixel"
							style={{
								fontSize: 10,
								color: "var(--lg-ink-mute)",
								marginBottom: 4,
							}}
						>
							ROW FILTER
						</div>
						<div
							className="mono"
							style={{
								fontSize: 10,
								padding: 8,
								border: "1px solid var(--lg-border)",
								background: "var(--lg-bg)",
								color: "var(--lg-amber)",
							}}
						>
							WHERE ACTV = 'Y' AND JOIN_DT &gt;= '1998-01-01'
						</div>
						<div style={{ fontSize: 10, color: "var(--lg-ink-dim)", marginTop: 6 }}>
							48,221 →{" "}
							<b style={{ color: "var(--lg-amber)" }}>46,084 kept</b>
						</div>
					</div>
				</div>
			</div>

			<div className="panel">
				<div className="panel-head">BEFORE / AFTER · SAMPLE 4 OF 48,221 ROWS</div>
				<div className="panel-body" style={{ padding: 0 }}>
					<div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 0 }}>
						<div style={{ borderRight: "1px solid var(--lg-border)" }}>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-ink-mute)",
									padding: "8px 10px",
									letterSpacing: "0.1em",
								}}
							>
								SOURCE · CUSTOMERS
							</div>
							<div style={{ overflow: "auto" }}>
								<table className="table">
									<thead>
										<tr>
											{COLS.map((cl) => (
												<th
													key={cl.n}
													className={
														cl.op === "drop"
															? "col-drop"
															: cl.op === "rename"
																? "col-rename"
																: cl.op === "cast"
																	? "col-cast"
																	: ""
													}
												>
													{cl.n}
												</th>
											))}
										</tr>
									</thead>
									<tbody>
										{ROWS.map((r, ri) => (
											<tr key={ri}>
												{r.map((v, ci) => (
													<td
														key={ci}
														className={
															COLS[ci].op === "drop"
																? "col-drop"
																: COLS[ci].op === "rename"
																	? "col-rename"
																	: COLS[ci].op === "cast"
																		? "col-cast"
																		: ""
														}
													>
														{v || "—"}
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
								style={{
									fontSize: 9,
									color: "var(--lg-amber)",
									padding: "8px 10px",
									letterSpacing: "0.1em",
								}}
							>
								→ OUTPUT · customers
							</div>
							<div style={{ overflow: "auto" }}>
								<table className="table">
									<thead>
										<tr>
											{kept.map((cl) => (
												<th
													key={cl.n}
													className={
														cl.op === "cast"
															? "col-cast"
															: cl.op === "rename"
																? "col-rename"
																: ""
													}
												>
													{afterName(cl)}
													<div
														style={{
															fontFamily: "var(--lg-mono)",
															fontSize: 9,
															color: "var(--lg-ink-mute)",
															fontWeight: 400,
															letterSpacing: 0,
														}}
													>
														{afterType(cl)}
													</div>
												</th>
											))}
											<th className="col-add">
												migrated_at
												<div
													style={{
														fontFamily: "var(--lg-mono)",
														fontSize: 9,
														letterSpacing: 0,
														fontWeight: 400,
													}}
												>
													TIMESTAMPTZ
												</div>
											</th>
										</tr>
									</thead>
									<tbody>
										{ROWS.map((r, ri) => (
											<tr key={ri}>
												{kept.map((cl) => (
													<td
														key={cl.n}
														className={
															cl.op === "cast"
																? "col-cast"
																: cl.op === "rename"
																	? "col-rename"
																	: ""
														}
													>
														{afterValue(r[cl.i], cl)}
													</td>
												))}
												<td className="col-add">2026-04-22T14:02Z</td>
											</tr>
										))}
									</tbody>
								</table>
							</div>
						</div>
					</div>
				</div>
			</div>

			<div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
				<button className="btn btn-ghost">SAVE AS RECIPE</button>
				<button className="btn btn-primary" onClick={onNext}>
					CONTINUE TO MAP <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- map (wired view) ----------

const MAP_SOURCES = [
	{ n: "customer_id", t: "BIGINT" },
	{ n: "display_name", t: "TEXT" },
	{ n: "address_line_1", t: "TEXT" },
	{ n: "city", t: "TEXT" },
	{ n: "region", t: "TEXT" },
	{ n: "joined_at", t: "TIMESTAMPTZ" },
	{ n: "credit_limit", t: "DECIMAL(12,2)" },
	{ n: "is_active", t: "BOOLEAN" },
	{ n: "migrated_at", t: "TIMESTAMPTZ" },
];

type MapTarget = {
	n: string;
	t: string;
	req: boolean;
	src: string | null;
	x: string | null;
};

const MAP_TARGETS: MapTarget[] = [
	{ n: "id", t: "bigint", req: true, src: "customer_id", x: "direct" },
	{ n: "name", t: "text", req: true, src: "display_name", x: "direct" },
	{ n: "address", t: "text", req: false, src: "address_line_1", x: "concat" },
	{ n: "city", t: "text", req: false, src: "city", x: "upper→title" },
	{ n: "state", t: "char(2)", req: false, src: "region", x: "lookup" },
	{ n: "signup_date", t: "date", req: true, src: "joined_at", x: "cast date" },
	{ n: "credit_limit", t: "numeric", req: false, src: "credit_limit", x: "direct" },
	{ n: "active", t: "boolean", req: true, src: "is_active", x: "direct" },
	{ n: "created_at", t: "timestamptz", req: true, src: "migrated_at", x: "direct" },
	{ n: "tenant_id", t: "text", req: true, src: null, x: "const" },
	{ n: "tier", t: "text", req: false, src: null, x: null },
];

function RlMap({ onNext }: { onNext: () => void }) {
	const SOURCES = MAP_SOURCES;
	const TARGETS = MAP_TARGETS;
	const [sel, setSel] = useState("address");
	const rowH = 40;
	const headH = 24;
	const mapped = TARGETS.filter((t) => t.src).length;
	const missing = TARGETS.filter((t) => t.req && !t.src).length;

	return (
		<div
			style={{
				marginTop: 14,
				display: "flex",
				flexDirection: "column",
				gap: 14,
			}}
		>
			<div style={{ display: "flex", alignItems: "center", gap: 10 }}>
				<select className="select" style={{ width: 280 }}>
					<option>postgres/crm_customer_v2 · 11 fields</option>
					<option>snowflake/sales_fact · 22 fields</option>
					<option>+ CREATE NEW TEMPLATE</option>
				</select>
				<div style={{ flex: 1 }} />
				<span className="badge badge-solid">
					<ICheck size={8} /> {mapped}/{TARGETS.length} MAPPED
				</span>
				{missing > 0 && (
					<span className="badge badge-err">{missing} REQ MISSING</span>
				)}
				<button className="btn btn-ghost">AUTO-MAP</button>
			</div>

			<div className="panel">
				<div className="panel-head">TARGET ← SOURCE · WIRED</div>
				<div className="panel-body">
					<div
						style={{
							display: "grid",
							gridTemplateColumns: "1fr 80px 1fr",
							gap: 0,
						}}
					>
						<div>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-ink-mute)",
									padding: "0 0 8px",
									letterSpacing: "0.1em",
								}}
							>
								SOURCE · customers (post-transform)
							</div>
							{SOURCES.map((s) => (
								<div
									key={s.n}
									className="rl-map-field"
									style={{ height: rowH - 4 }}
								>
									<div style={{ fontFamily: "var(--lg-mono)", fontSize: 11 }}>
										{s.n}
									</div>
									<div style={{ fontSize: 9, color: "var(--lg-ink-mute)" }}>
										{s.t}
									</div>
								</div>
							))}
						</div>
						<div style={{ position: "relative" }}>
							<svg
								viewBox={`0 0 80 ${headH + TARGETS.length * rowH}`}
								preserveAspectRatio="none"
								style={{
									position: "absolute",
									inset: 0,
									width: "100%",
									height: "100%",
								}}
							>
								{TARGETS.map((t, ti) => {
									if (!t.src) return null;
									const si = SOURCES.findIndex((s) => s.n === t.src);
									if (si < 0) return null;
									const y1 = headH + si * rowH + rowH / 2;
									const y2 = headH + ti * rowH + rowH / 2;
									const isSel = t.n === sel;
									return (
										<path
											key={t.n}
											d={`M0,${y1} C40,${y1} 40,${y2} 80,${y2}`}
											fill="none"
											stroke={
												isSel ? "var(--lg-amber)" : "var(--lg-amber-dim)"
											}
											strokeWidth={isSel ? 2 : 1}
											opacity={isSel ? 1 : 0.55}
											shapeRendering="crispEdges"
										/>
									);
								})}
								{TARGETS.map((t, ti) => {
									if (t.src) return null;
									const y2 = headH + ti * rowH + rowH / 2;
									return (
										<path
											key={t.n}
											d={`M30,${y2} L80,${y2}`}
											stroke="var(--lg-coral)"
											strokeWidth={1}
											strokeDasharray="2 2"
											fill="none"
										/>
									);
								})}
							</svg>
						</div>
						<div>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-amber)",
									padding: "0 0 8px",
									letterSpacing: "0.1em",
								}}
							>
								→ TARGET · crm_customer_v2
							</div>
							{TARGETS.map((t) => {
								const isSel = t.n === sel;
								return (
									<div
										key={t.n}
										onClick={() => setSel(t.n)}
										className={`rl-map-field tgt ${isSel ? "selected" : ""} ${!t.src ? "unmapped" : ""}`}
										style={{ height: rowH - 4 }}
									>
										<div
											style={{
												display: "flex",
												justifyContent: "space-between",
												alignItems: "baseline",
											}}
										>
											<div
												style={{
													fontFamily: "var(--lg-mono)",
													fontSize: 11,
												}}
											>
												{t.n}
												{t.req && (
													<span
														style={{
															color: "var(--lg-coral)",
															marginLeft: 3,
														}}
													>
														*
													</span>
												)}
											</div>
											<div
												style={{ fontSize: 9, color: "var(--lg-ink-mute)" }}
											>
												{t.t}
											</div>
										</div>
										<div
											style={{
												fontSize: 9,
												color: t.src ? "var(--lg-ink-dim)" : "var(--lg-coral)",
												fontFamily: "var(--lg-mono)",
											}}
										>
											{t.src ? (
												<>
													← {t.src} ·{" "}
													<span style={{ color: "var(--lg-amber)" }}>
														ƒ {t.x}
													</span>
												</>
											) : (
												"UNMAPPED · PICK A SOURCE"
											)}
										</div>
									</div>
								);
							})}
						</div>
					</div>
				</div>
			</div>

			<div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
				<button className="btn btn-ghost">VALIDATE</button>
				<button className="btn btn-primary" onClick={onNext}>
					CONTINUE TO EXPORT <IArrow size={10} />
				</button>
			</div>
		</div>
	);
}

// ---------- export ----------

const EXPORT_PREV: Record<string, string> = {
	csv: `customer_id,display_name,city,region,joined_at,credit_limit,is_active,migrated_at
10045,"ACME NORTHWIND","PORTLAND","OR",1998-04-12T00:00:00Z,5000.00,true,2026-04-22T14:02Z
10046,"BOB'S TOOLS","EUGENE","OR",1998-04-18T00:00:00Z,2500.00,true,2026-04-22T14:02Z
10047,"CEDAR CO.","SALEM","OR",1998-05-02T00:00:00Z,10000.00,false,2026-04-22T14:02Z
…
48,218 more rows`,
	"sql-insert": `INSERT INTO customer_v2 (customer_id, display_name, city, region, joined_at, credit_limit, is_active) VALUES
  (10045, 'ACME NORTHWIND', 'PORTLAND', 'OR', '1998-04-12'::timestamptz, 5000.00, true),
  (10046, 'BOB''S TOOLS',   'EUGENE',   'OR', '1998-04-18'::timestamptz, 2500.00, true),
  (10047, 'CEDAR CO.',      'SALEM',    'OR', '1998-05-02'::timestamptz,10000.00, false);
-- 48,221 rows in 483 batches`,
	"sql-full": `CREATE TABLE customer_v2 (
  customer_id   BIGINT       PRIMARY KEY,
  display_name  TEXT         NOT NULL,
  city          TEXT,
  region        TEXT,
  joined_at     TIMESTAMPTZ  NOT NULL,
  credit_limit  NUMERIC(12,2),
  is_active     BOOLEAN      NOT NULL,
  migrated_at   TIMESTAMPTZ  NOT NULL
);

INSERT INTO customer_v2 VALUES (10045, 'ACME NORTHWIND', ...);`,
	json: `{"customer_id":10045,"display_name":"ACME NORTHWIND","city":"PORTLAND","is_active":true}
{"customer_id":10046,"display_name":"BOB'S TOOLS","city":"EUGENE","is_active":true}
…`,
	db: `-- target: postgres://prod-db/public
-- streaming 48,221 rows via COPY
[ connection : established  ✓ ]
[ schema     : customer_v2 exists ✓ ]
[ conflict   : ON CONFLICT DO UPDATE ]

> Press RUN to stream.`,
};

function RlExport({ onDone }: { onDone: () => void }) {
	const [fmt, setFmt] = useState("csv");
	const FORMATS = [
		{ id: "csv", label: "CSV", sub: "Comma-separated · UTF-8" },
		{ id: "sql-insert", label: "SQL · INSERTS", sub: "INSERT INTO … VALUES" },
		{ id: "sql-full", label: "SQL · FULL", sub: "CREATE + INSERTS" },
		{ id: "json", label: "JSON", sub: "One object per row" },
		{ id: "db", label: "DIRECT TO DB", sub: "Stream via connection" },
	];
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
							onClick={() => setFmt(f.id)}
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
						PREVIEW · customers.
						{fmt === "csv"
							? "csv"
							: fmt === "json"
								? "json"
								: fmt === "db"
									? "stream"
									: "sql"}
					</span>
					<span className="badge badge-mute">48,221 ROWS · ≈7.4 MB</span>
				</div>
				<pre
					style={{
						margin: 0,
						padding: 14,
						fontSize: 11,
						lineHeight: 1.7,
						fontFamily: "var(--lg-mono)",
						color: "var(--lg-amber)",
						background: "#000",
						minHeight: 340,
						whiteSpace: "pre-wrap",
						overflow: "auto",
					}}
				>
					{EXPORT_PREV[fmt]}
				</pre>
			</div>
			<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
				<div className="panel">
					<div className="panel-head">READY TO RUN</div>
					<div className="panel-body">
						<div
							className="pixel"
							style={{ fontSize: 22, color: "var(--lg-amber)" }}
						>
							48,221
						</div>
						<div
							className="mono"
							style={{ fontSize: 11, color: "var(--lg-ink-dim)" }}
						>
							ROWS WILL MIGRATE
						</div>
					</div>
				</div>
				<div className="panel">
					<div className="panel-head">OPTIONS</div>
					<div className="panel-body">
						<dl className="kv">
							<dt>BATCH</dt>
							<dd>100 rows</dd>
							<dt>ENCODING</dt>
							<dd>UTF-8</dd>
							<dt>ON ERROR</dt>
							<dd>halt + log</dd>
							<dt>DELIMITER</dt>
							<dd>{fmt === "csv" ? "," : "—"}</dd>
						</dl>
					</div>
				</div>
				<button className="btn btn-primary" onClick={onDone}>
					▶ RUN PIPELINE
				</button>
				<button className="btn btn-ghost">DOWNLOAD SAMPLE</button>
			</div>
		</div>
	);
}

// ---------- pipeline wrapper ----------

export function RlPipeline({
	project,
	stage,
	setStage,
	onBack,
}: {
	project: Project | null;
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
		<PipelineProvider>
			<div className="rl-page">
				<RlTopbar
					title={project?.name || "NEW PROJECT"}
					sub={
						project && project.source !== "—"
							? `${project.source}  →  ${project.target}`
							: "NOT STARTED"
					}
					right={
						<>
							<button className="btn btn-ghost" onClick={onBack}>
								← PROJECTS
							</button>
							{project?.status === "running" && (
								<span className="badge badge-ok">
									<IDot size={6} /> RUNNING
								</span>
							)}
							{project?.status === "done" && (
								<span className="badge badge-solid">DONE</span>
							)}
							{project?.status === "error" && (
								<span className="badge badge-err">ERROR</span>
							)}
						</>
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
