import { useEffect, useRef, useState } from "react";
import { IDisk, IPlus, IX, ICheck, IUpload } from "./icons";
import { SpriteGhost, Sparkles } from "./Sprites";
import { RlTopbar } from "./Topbar";

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

const LS_DDL = "retro-legacy.v2.ddl-templates";

function loadDDLs(): DDLEntry[] {
	try {
		const raw = localStorage.getItem(LS_DDL);
		if (raw) return JSON.parse(raw) as DDLEntry[];
	} catch {}
	return [];
}

function saveDDLs(entries: DDLEntry[]) {
	localStorage.setItem(LS_DDL, JSON.stringify(entries));
}

export function RlTemplates() {
	const [entries, setEntries] = useState<DDLEntry[]>(loadDDLs);
	const [sel, setSel] = useState<string | null>(entries[0]?.id ?? null);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const inputRef = useRef<HTMLInputElement | null>(null);

	useEffect(() => {
		saveDDLs(entries);
	}, [entries]);

	const selected = entries.find((e) => e.id === sel);
	const isEmpty = entries.length === 0;

	const handleUpload = async (files: FileList | null) => {
		if (!files || files.length === 0) return;
		setUploading(true);
		setError(null);

		try {
			// We need a session to upload DDL. Create a temporary one or use
			// a lightweight parse. For now, we parse locally by sending to
			// a temporary upload session.
			const form = new FormData();
			for (const f of Array.from(files)) {
				form.append("files", f);
			}

			// Upload a dummy CSV to get a session, then upload DDL to that session
			// Actually, let's just store the DDL file content and parse table names client-side
			// since the DDL upload endpoint requires a session_id.
			// We'll read the files and extract CREATE TABLE names.
			for (const file of Array.from(files)) {
				const content = await file.text();
				const tableMatches = content.matchAll(
					/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["'`]?(\w+)["'`]?\s*\(/gi,
				);
				const schema: DDLSchema = {};
				for (const match of tableMatches) {
					const tableName = match[1];
					// Extract columns between the parens
					const startIdx = match.index! + match[0].length;
					let depth = 1;
					let endIdx = startIdx;
					for (let i = startIdx; i < content.length && depth > 0; i++) {
						if (content[i] === "(") depth++;
						if (content[i] === ")") depth--;
						if (depth === 0) endIdx = i;
					}
					const colBlock = content.slice(startIdx, endIdx);
					const colDefs = colBlock.split(",").map((s) => s.trim()).filter(Boolean);
					const columns: Record<string, DDLColumn> = {};
					for (const def of colDefs) {
						const parts = def.split(/\s+/);
						if (parts.length < 2) continue;
						const colName = parts[0].replace(/["'`]/g, "");
						// Skip constraint keywords
						if (
							["PRIMARY", "FOREIGN", "UNIQUE", "INDEX", "KEY", "CONSTRAINT", "CHECK"].includes(
								colName.toUpperCase(),
							)
						)
							continue;
						const colType = parts[1].replace(/["'`]/g, "");
						const nullable = !def.toUpperCase().includes("NOT NULL");
						columns[colName] = {
							inferred_type: colType.toLowerCase(),
							original_type: colType,
							nullable,
						};
					}
					if (Object.keys(columns).length > 0) {
						schema[tableName] = columns;
					}
				}

				if (Object.keys(schema).length === 0) {
					setError("No CREATE TABLE statements found in " + file.name);
					continue;
				}

				const entry: DDLEntry = {
					id: crypto.randomUUID(),
					name: file.name.replace(/\.(sql|ddl|txt)$/i, "").toUpperCase(),
					schema,
					matchingTables: [],
					uploadedAt: new Date().toISOString(),
				};
				setEntries((prev) => [...prev, entry]);
				setSel(entry.id);
			}
		} catch {
			setError("Failed to parse DDL file");
		} finally {
			setUploading(false);
		}
	};

	const handleDelete = (id: string) => {
		setEntries((prev) => prev.filter((e) => e.id !== id));
		if (sel === id) setSel(entries.find((e) => e.id !== id)?.id ?? null);
	};

	const tableCount = selected
		? Object.keys(selected.schema).length
		: 0;
	const colCount = selected
		? Object.values(selected.schema).reduce(
				(a, cols) => a + Object.keys(cols).length,
				0,
			)
		: 0;

	return (
		<div className="rl-page">
			<RlTopbar
				title="TEMPLATES"
				sub="DDL SCHEMAS · UPLOAD SQL TO DEFINE TARGET STRUCTURE"
				right={
					<>
						<button
							className="btn btn-primary"
							onClick={() => inputRef.current?.click()}
							disabled={uploading}
						>
							<IUpload size={10} /> {uploading ? "PARSING…" : "UPLOAD DDL"}
						</button>
						<input
							ref={inputRef}
							type="file"
							accept=".sql,.ddl,.txt"
							multiple
							onChange={(e) => {
								handleUpload(e.target.files);
								e.target.value = "";
							}}
							style={{ display: "none" }}
						/>
					</>
				}
			/>

			{error && (
				<div
					className="panel"
					style={{ padding: "10px 14px", marginBottom: 14 }}
				>
					<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>
						{"> "}{error}
					</div>
				</div>
			)}

			{isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot">
							<SpriteGhost size={80} color="amber" />
						</div>
						<div className="rl-empty-title">NO TEMPLATES YET</div>
						<div className="rl-empty-sub">
							Upload a .SQL file with CREATE TABLE statements to define target
							schemas. These can be applied to projects during the Map stage to
							enforce column types and structure.
						</div>
						<button
							className="btn btn-primary"
							onClick={() => inputRef.current?.click()}
						>
							<IUpload size={10} /> UPLOAD DDL FILE
						</button>
					</div>
				</div>
			) : (
				<div
					style={{
						display: "grid",
						gridTemplateColumns: "1fr 420px",
						gap: 16,
					}}
				>
					<div className="rl-tpl-grid">
						{entries.map((tp) => {
							const active = tp.id === sel;
							const tables = Object.keys(tp.schema);
							return (
								<div
									key={tp.id}
									className={`rl-tpl ${active ? "active" : ""}`}
									onClick={() => setSel(tp.id)}
								>
									<div
										style={{
											display: "flex",
											gap: 10,
											alignItems: "flex-start",
										}}
									>
										<IDisk size={14} />
										<div style={{ flex: 1 }}>
											<div
												className="pixel"
												style={{
													fontSize: 10,
													color: "var(--lg-amber)",
												}}
											>
												{tp.name}
											</div>
											<div
												className="mono"
												style={{
													fontSize: 11,
													color: "var(--lg-ink-dim)",
													marginTop: 4,
												}}
											>
												{tables.length} table{tables.length === 1 ? "" : "s"} ·{" "}
												{Object.values(tp.schema).reduce(
													(a, c) => a + Object.keys(c).length,
													0,
												)}{" "}
												columns
											</div>
										</div>
										<button
											className="link"
											style={{ fontSize: 9, color: "var(--lg-coral)" }}
											onClick={(e) => {
												e.stopPropagation();
												handleDelete(tp.id);
											}}
											title="Delete"
										>
											<IX size={8} />
										</button>
									</div>
									<div
										style={{
											display: "flex",
											gap: 4,
											flexWrap: "wrap",
											marginTop: 8,
										}}
									>
										{tables.slice(0, 5).map((t) => (
											<span key={t} className="badge badge-mute">
												{t}
											</span>
										))}
										{tables.length > 5 && (
											<span className="badge badge-mute">
												+{tables.length - 5}
											</span>
										)}
									</div>
								</div>
							);
						})}
					</div>

					{selected && (
						<div
							style={{
								display: "flex",
								flexDirection: "column",
								gap: 14,
							}}
						>
							<div className="panel">
								<div className="panel-head">
									<IDisk size={10} /> {selected.name}
								</div>
								<div className="panel-body">
									<dl className="kv">
										<dt>TABLES</dt>
										<dd>{tableCount}</dd>
										<dt>COLUMNS</dt>
										<dd>{colCount}</dd>
										<dt>UPLOADED</dt>
										<dd>
											{new Date(selected.uploadedAt).toLocaleDateString()}
										</dd>
									</dl>
								</div>
							</div>

							{Object.entries(selected.schema).map(
								([tableName, columns]) => (
									<div key={tableName} className="panel">
										<div className="panel-head">
											<ICheck size={10} /> {tableName.toUpperCase()}
											<span
												className="badge badge-mute"
												style={{ marginLeft: 8 }}
											>
												{Object.keys(columns).length} COLS
											</span>
										</div>
										<div
											className="panel-body"
											style={{ padding: 0 }}
										>
											{Object.entries(columns).map(
												([colName, col]) => (
													<div
														key={colName}
														className="rl-col-row"
													>
														<div
															style={{
																flex: 1.4,
																fontFamily:
																	"var(--lg-pixel)",
																fontSize: 9,
																color: "var(--lg-ink)",
															}}
														>
															{colName}
														</div>
														<div
															style={{
																flex: 1,
																fontFamily:
																	"var(--lg-mono)",
																fontSize: 10,
																color: "var(--lg-ink-dim)",
															}}
														>
															{col.original_type.toUpperCase()}
														</div>
														<div
															style={{
																width: 80,
																textAlign: "right",
															}}
														>
															<span
																className={`badge ${col.nullable ? "badge-mute" : "badge-warn"}`}
															>
																{col.nullable
																	? "NULL"
																	: "NOT NULL"}
															</span>
														</div>
													</div>
												),
											)}
										</div>
									</div>
								),
							)}
						</div>
					)}
				</div>
			)}
		</div>
	);
}
