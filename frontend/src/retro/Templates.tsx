import { useEffect, useRef, useState, useCallback } from "react";
import { IDisk, IX, ICheck, IUpload } from "./icons";
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

// ---------- Main component ----------
export function RlTemplates() {
	const [entries, setEntries] = useState<DDLEntry[]>(loadDDLs);
	const [sel, setSel] = useState<string | null>(entries[0]?.id ?? null);
	const [uploading, setUploading] = useState(false);
	const [error, setError] = useState<string | null>(null);
	const inputRef = useRef<HTMLInputElement | null>(null);

	// Edit state
	const [selectedTable, setSelectedTable] = useState<string | null>(null);
	const [expandedTable, setExpandedTable] = useState<string | null>(null);
	const [editingTemplateName, setEditingTemplateName] = useState(false);
	const [tempName, setTempName] = useState("");
	const [renamingTable, setRenamingTable] = useState<string | null>(null);
	const [renamingCol, setRenamingCol] = useState<{ table: string; col: string } | null>(null);
	const [tempRename, setTempRename] = useState("");

	useEffect(() => { saveDDLs(entries); }, [entries]);

	useEffect(() => {
		setSelectedTable(null);
		setExpandedTable(null);
	}, [sel]);

	const selected = entries.find((e) => e.id === sel);
	const isEmpty = entries.length === 0;

	const handleUpload = async (files: FileList | null) => {
		if (!files || files.length === 0) return;
		setUploading(true);
		setError(null);
		try {
			for (const file of Array.from(files)) {
				const content = await file.text();
				const tableMatches = content.matchAll(
					/CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`([^`]+)`|"([^"]+)"|([^\s(]+))\s*\(/gi,
				);
				const schema: DDLSchema = {};
				for (const match of tableMatches) {
					const tableName = match[1] || match[2] || match[3];
					const startIdx = match.index! + match[0].length;
					let depth = 1, endIdx = startIdx;
					for (let i = startIdx; i < content.length && depth > 0; i++) {
						if (content[i] === "(") depth++;
						if (content[i] === ")") depth--;
						if (depth === 0) endIdx = i;
					}
					const colBlock = content.slice(startIdx, endIdx);
					const columns: Record<string, DDLColumn> = {};
					for (const def of colBlock.split(",").map((s) => s.trim()).filter(Boolean)) {
						const parts = def.split(/\s+/);
						if (parts.length < 2) continue;
						const colName = parts[0].replace(/["'`]/g, "");
						if (["PRIMARY", "FOREIGN", "UNIQUE", "INDEX", "KEY", "CONSTRAINT", "CHECK"].includes(colName.toUpperCase())) continue;
						const colType = parts[1].replace(/["'`]/g, "");
						columns[colName] = { inferred_type: colType.toLowerCase(), original_type: colType, nullable: !def.toUpperCase().includes("NOT NULL") };
					}
					if (Object.keys(columns).length > 0) schema[tableName] = columns;
				}
				if (Object.keys(schema).length === 0) { setError("No CREATE TABLE statements found in " + file.name); continue; }
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
		} catch { setError("Failed to parse DDL file"); }
		finally { setUploading(false); }
	};

	const handleDelete = (id: string) => {
		setEntries((prev) => prev.filter((e) => e.id !== id));
		if (sel === id) setSel(entries.find((e) => e.id !== id)?.id ?? null);
	};

	const commitRenameTemplate = () => {
		const name = tempName.trim().toUpperCase();
		if (name && selected) setEntries((prev) => prev.map((e) => e.id === sel ? { ...e, name } : e));
		setEditingTemplateName(false);
	};

	const handleDropTable = useCallback((tableName: string) => {
		if (!sel) return;
		setEntries((prev) => prev.map((e) => {
			if (e.id !== sel) return e;
			const schema = { ...e.schema };
			delete schema[tableName];
			return { ...e, schema };
		}));
		if (selectedTable === tableName) setSelectedTable(null);
		if (expandedTable === tableName) setExpandedTable(null);
	}, [sel, selectedTable, expandedTable]);

	const handleRenameTable = useCallback((tableName: string) => {
		setRenamingTable(tableName);
		setTempRename(tableName);
	}, []);

	const commitRenameTable = () => {
		const newName = tempRename.trim();
		if (!newName || !sel || !renamingTable || newName === renamingTable) { setRenamingTable(null); return; }
		setEntries((prev) => prev.map((e) => {
			if (e.id !== sel) return e;
			const schema: DDLSchema = {};
			for (const [k, v] of Object.entries(e.schema)) schema[k === renamingTable ? newName : k] = v;
			return { ...e, schema };
		}));
		if (selectedTable === renamingTable) setSelectedTable(newName);
		if (expandedTable === renamingTable) setExpandedTable(newName);
		setRenamingTable(null);
	};

	const handleDropColumn = useCallback((tableName: string, colName: string) => {
		if (!sel) return;
		setEntries((prev) => prev.map((e) => {
			if (e.id !== sel) return e;
			const schema = { ...e.schema, [tableName]: { ...e.schema[tableName] } };
			delete schema[tableName][colName];
			return { ...e, schema };
		}));
	}, [sel]);

	const handleRenameColumn = useCallback((tableName: string, colName: string) => {
		setRenamingCol({ table: tableName, col: colName });
		setTempRename(colName);
	}, []);

	const commitRenameColumn = () => {
		const newName = tempRename.trim();
		if (!newName || !sel || !renamingCol || newName === renamingCol.col) { setRenamingCol(null); return; }
		setEntries((prev) => prev.map((e) => {
			if (e.id !== sel) return e;
			const cols: Record<string, DDLColumn> = {};
			for (const [k, v] of Object.entries(e.schema[renamingCol.table])) cols[k === renamingCol.col ? newName : k] = v;
			const schema = { ...e.schema, [renamingCol.table]: cols };
			return { ...e, schema };
		}));
		setRenamingCol(null);
	};

	const handleToggleNullable = useCallback((tableName: string, colName: string) => {
		if (!sel) return;
		setEntries((prev) => prev.map((e) => {
			if (e.id !== sel) return e;
			const col = e.schema[tableName][colName];
			return { ...e, schema: { ...e.schema, [tableName]: { ...e.schema[tableName], [colName]: { ...col, nullable: !col.nullable } } } };
		}));
	}, [sel]);

	// Keyboard shortcuts
	useEffect(() => {
		if (!selected) return;
		const tables = Object.keys(selected.schema);
		const handler = (e: KeyboardEvent) => {
			if (renamingTable || renamingCol || editingTemplateName) return;
			const tag = (e.target as HTMLElement).tagName;
			if (tag === "INPUT" || tag === "TEXTAREA") return;
			const key = e.key.toLowerCase();
			const idx = selectedTable ? tables.indexOf(selectedTable) : -1;
			if (key === "arrowup") { e.preventDefault(); setSelectedTable(tables[Math.max(0, idx > 0 ? idx - 1 : tables.length - 1)]); }
			else if (key === "arrowdown") { e.preventDefault(); setSelectedTable(tables[Math.min(tables.length - 1, idx < 0 ? 0 : idx + 1)]); }
			else if (key === " " && selectedTable) { e.preventDefault(); setExpandedTable(selectedTable); }
			else if (key === "escape" && expandedTable) { e.preventDefault(); setExpandedTable(null); }
			else if (key === "r" && selectedTable) { e.preventDefault(); handleRenameTable(selectedTable); }
			else if (key === "d" && selectedTable) { e.preventDefault(); handleDropTable(selectedTable); }
		};
		window.addEventListener("keydown", handler);
		return () => window.removeEventListener("keydown", handler);
	}, [selected, selectedTable, expandedTable, renamingTable, renamingCol, editingTemplateName, handleRenameTable, handleDropTable]);

	const tableCount = selected ? Object.keys(selected.schema).length : 0;
	const colCount = selected ? Object.values(selected.schema).reduce((a, c) => a + Object.keys(c).length, 0) : 0;

	const colModalContent = expandedTable && selected?.schema[expandedTable] ? (
		<>
			<div
				className="panel"
				style={{ width: "min(680px, 90vw)", maxHeight: "70vh", display: "flex", flexDirection: "column", boxShadow: "4px 4px 0 #0a0805, 0 0 0 1px var(--lg-amber)" }}
				onClick={(e) => e.stopPropagation()}
			>
				<div className="panel-head" style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
					<ICheck size={10} />
					<span style={{ flex: 1 }}>{expandedTable.toUpperCase()}</span>
					<span className="badge badge-mute">{Object.keys(selected.schema[expandedTable]).length} COLS</span>
					<button className="link" style={{ color: "var(--lg-coral)", fontSize: 10, marginLeft: 8 }} onClick={() => setExpandedTable(null)}><IX size={9} /></button>
				</div>

				<div style={{ overflowY: "auto", flex: 1 }}>
					{Object.entries(selected.schema[expandedTable]).map(([colName, col]) => {
						const isRenamingCol = renamingCol?.table === expandedTable && renamingCol?.col === colName;
						return (
							<div key={colName} className="rl-col-row">
								<div style={{ flex: 1.6, display: "flex", alignItems: "center", gap: 6, minWidth: 0 }}>
									{isRenamingCol ? (
										<input autoFocus value={tempRename}
											onChange={(e) => setTempRename(e.target.value)}
											onBlur={commitRenameColumn}
											onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") commitRenameColumn(); if (e.key === "Escape") setRenamingCol(null); }}
											style={{ fontFamily: "var(--lg-pixel)", fontSize: 10, background: "transparent", border: "1px solid var(--lg-amber)", color: "var(--lg-amber)", padding: "2px 6px", width: "100%" }}
										/>
									) : (
										<span style={{ fontFamily: "var(--lg-pixel)", fontSize: 10, color: "var(--lg-ink)", overflow: "hidden", textOverflow: "ellipsis" }} title={colName}>
											{colName}
										</span>
									)}
								</div>
								<div style={{ flex: 1, fontFamily: "var(--lg-mono)", fontSize: 11, color: "var(--lg-ink-dim)" }}>
									{col.original_type.toUpperCase()}
								</div>
								<div style={{ display: "flex", gap: 6, alignItems: "center" }}>
									<span className={`badge ${col.nullable ? "badge-mute" : "badge-warn"}`}
										style={{ cursor: "pointer" }}
										onClick={() => handleToggleNullable(expandedTable, colName)}
										title="Click to toggle">
										{col.nullable ? "NULL" : "NOT NULL"}
									</span>
									<button className="link" style={{ fontSize: 9, color: "var(--lg-ink-dim)" }} onClick={() => handleRenameColumn(expandedTable, colName)}>[R]</button>
									<button className="link" style={{ fontSize: 9, color: "var(--lg-coral)" }} onClick={() => handleDropColumn(expandedTable, colName)}>[D]</button>
								</div>
							</div>
						);
					})}
				</div>

				<div style={{ padding: "8px 12px", borderTop: "1px solid var(--lg-border)", display: "flex", justifyContent: "flex-end", flexShrink: 0 }}>
					<button className="btn btn-ghost" style={{ fontSize: 9, padding: "3px 12px" }} onClick={() => setExpandedTable(null)}>CLOSE [Esc]</button>
				</div>
			</div>
		</>
	) : null;

	return (
		<>
		<div className="rl-page">
			<RlTopbar
				title="TEMPLATES"
				sub="DDL SCHEMAS · UPLOAD SQL TO DEFINE TARGET STRUCTURE"
				right={
					<>
						<button className="btn btn-primary" onClick={() => inputRef.current?.click()} disabled={uploading}>
							<IUpload size={10} /> {uploading ? "PARSING…" : "UPLOAD DDL"}
						</button>
						<input ref={inputRef} type="file" accept=".sql,.ddl,.txt" multiple
							onChange={(e) => { handleUpload(e.target.files); e.target.value = ""; }}
							style={{ display: "none" }}
						/>
					</>
				}
			/>

			{error && (
				<div className="panel" style={{ padding: "10px 14px", marginBottom: 14 }}>
					<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>{">"} {error}</div>
				</div>
			)}

			{isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot"><SpriteGhost size={80} color="amber" /></div>
						<div className="rl-empty-title">NO TEMPLATES YET</div>
						<div className="rl-empty-sub">Upload a .SQL file with CREATE TABLE statements to define target schemas.</div>
						<button className="btn btn-primary" onClick={() => inputRef.current?.click()}><IUpload size={10} /> UPLOAD DDL FILE</button>
					</div>
				</div>
			) : (
				<div style={{ display: "grid", gridTemplateColumns: "220px 1fr", gap: 16 }}>
					{/* Left: template list */}
					<div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
						{entries.map((tp) => {
							const active = tp.id === sel;
							const tables = Object.keys(tp.schema);
							return (
								<div key={tp.id} className={`rl-tpl ${active ? "active" : ""}`} onClick={() => setSel(tp.id)}>
									<div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
										<IDisk size={14} />
										<div style={{ flex: 1 }}>
											<div className="pixel" style={{ fontSize: 9, color: "var(--lg-amber)" }}>{tp.name}</div>
											<div className="mono" style={{ fontSize: 11, color: "var(--lg-ink-dim)", marginTop: 4 }}>
												{tables.length} tables · {Object.values(tp.schema).reduce((a, c) => a + Object.keys(c).length, 0)} cols
											</div>
										</div>
										<button className="link" style={{ fontSize: 9, color: "var(--lg-coral)" }}
											onClick={(e) => { e.stopPropagation(); handleDelete(tp.id); }} title="Delete">
											<IX size={8} />
										</button>
									</div>
									<div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
										{tables.slice(0, 4).map((t) => <span key={t} className="badge badge-mute">{t}</span>)}
										{tables.length > 4 && <span className="badge badge-mute">+{tables.length - 4}</span>}
									</div>
								</div>
							);
						})}
					</div>

					{/* Right: editor */}
					{selected && (
						<div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
							{/* Header bar */}
							<div className="panel">
								<div className="panel-head" style={{ display: "flex", alignItems: "center", gap: 8 }}>
									<IDisk size={10} />
									{editingTemplateName ? (
										<input autoFocus
											value={tempName}
											onChange={(e) => setTempName(e.target.value)}
											onBlur={commitRenameTemplate}
											onKeyDown={(e) => { if (e.key === "Enter") commitRenameTemplate(); if (e.key === "Escape") setEditingTemplateName(false); }}
											style={{ fontFamily: "var(--lg-pixel)", fontSize: 9, background: "transparent", border: "1px solid var(--lg-amber)", color: "var(--lg-amber)", padding: "1px 6px", width: 180 }}
										/>
									) : (
										<span style={{ cursor: "pointer", borderBottom: "1px dashed var(--lg-border-br)" }}
											onClick={() => { setTempName(selected.name); setEditingTemplateName(true); }}
											title="Click to rename">
											{selected.name}
										</span>
									)}
									<div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
										<span className="badge badge-mute">{tableCount} TBL</span>
										<span className="badge badge-mute">{colCount} COL</span>
									</div>
								</div>
							</div>

							{/* Table cards grid */}
							<div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 8 }}>
								{Object.entries(selected.schema).map(([tableName, columns]) => {
									const isSelected = selectedTable === tableName;
									const isRenaming = renamingTable === tableName;

									return (
										<div key={tableName} className="panel"
											style={{ border: isSelected ? "1px solid var(--lg-amber)" : undefined, cursor: "pointer" }}
											onClick={() => { setSelectedTable(tableName); setExpandedTable(tableName); }}
										>
											<div className="panel-head" style={{ display: "flex", alignItems: "center", gap: 6 }}>
												<ICheck size={10} />
												{isRenaming ? (
													<input autoFocus value={tempRename}
														onChange={(e) => setTempRename(e.target.value)}
														onBlur={commitRenameTable}
														onKeyDown={(e) => { e.stopPropagation(); if (e.key === "Enter") commitRenameTable(); if (e.key === "Escape") setRenamingTable(null); }}
														onClick={(e) => e.stopPropagation()}
														style={{ fontFamily: "var(--lg-pixel)", fontSize: 9, background: "transparent", border: "1px solid var(--lg-amber)", color: "var(--lg-amber)", padding: "1px 4px", flex: 1, minWidth: 0 }}
													/>
												) : (
													<span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
														{tableName.toUpperCase()}
													</span>
												)}
												<span className="badge badge-mute" style={{ fontSize: 8, flexShrink: 0 }}>{Object.keys(columns).length}</span>
											</div>

											<div style={{ display: "flex", gap: 4, padding: "6px 12px" }} onClick={(e) => e.stopPropagation()}>
												<button className="btn btn-ghost" style={{ fontSize: 8, padding: "2px 8px" }} onClick={() => handleRenameTable(tableName)}>[R]</button>
												<button className="btn btn-ghost" style={{ fontSize: 8, padding: "2px 8px", color: "var(--lg-coral)" }} onClick={() => handleDropTable(tableName)}>[D]</button>
											</div>
										</div>
									);
								})}
							</div>

						</div>
					)}
				</div>
			)}
		</div>
		{colModalContent && (
			<dialog
				ref={(el) => { if (el && !el.open) el.showModal(); }}
				className="rl-col-dialog"
				onCancel={(e) => { e.preventDefault(); setExpandedTable(null); }}
				onClick={(e) => { if (e.target === e.currentTarget) setExpandedTable(null); }}
			>
				{colModalContent}
			</dialog>
		)}
		</>
	);
}
