import { useState, useRef, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { IDisk, IX } from '../icons';
import { usePipelineCtx } from './context';

type PageData = {
	rows: Record<string, unknown>[];
	columns: string[];
	page: number;
	total_rows: number;
	total_pages: number;
};

export function TablePreviewModal({
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
				throw new Error(err?.detail || 'Failed to load data');
			}
			const d = await res.json();
			setData(d);
			setPage(d.page);
			setEditedRows(d.rows.map((r: Record<string, unknown>) => ({ ...r })));
			setDirty(false);
		} catch (e) {
			setError(e instanceof Error ? e.message : 'Load failed');
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
			if (!allRes.ok) throw new Error('Failed to load full data');
			const allData = await allRes.json();
			const allRows: Record<string, unknown>[] = allData.tables[tableName] ?? [];
			const start = (page - 1) * 100;
			for (let i = 0; i < editedRows.length; i++) {
				allRows[start + i] = editedRows[i];
			}
			const res = await fetch(`/api/table-data/${sessionId}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ tables: { [tableName]: allRows } }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail || 'Save failed');
			}
			const saveData = await res.json();
			setDirty(false);

			// Propagate updated data to pipeline context
			if (uploadResult && saveData.preview && saveData.schema) {
				const updatedTables = uploadResult.tables.map((t) => ({
					...t,
					rowCount: saveData.stats?.[t.name]?.row_count ?? t.rowCount,
					colCount: Object.keys(saveData.schema[t.name] ?? {}).length || t.colCount,
					columns:
						Object.keys(saveData.schema[t.name] ?? {}).length > 0
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
			setError(e instanceof Error ? e.message : 'Save failed');
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
		focusedCellRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
	}, [focusedRow, focusedCol]);

	// Keyboard navigation. Uses capture phase + stopPropagation so the
	// modal swallows keys before any parent (e.g. RlExtract's window
	// listener) can react to them.
	useEffect(() => {
		const handler = (e: KeyboardEvent) => {
			const tag = (e.target as HTMLElement).tagName;
			const isInputFocused = tag === 'INPUT' || tag === 'TEXTAREA';

			// Allow inputs to handle their own keys, except Escape to cancel edit
			if (isInputFocused) {
				if (e.key === 'Escape') {
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
				case 'ArrowUp':
					setFocusedRow((r) => Math.max(0, r - 1));
					break;
				case 'ArrowDown':
					setFocusedRow((r) => Math.min(rowCount - 1, r + 1));
					break;
				case 'ArrowLeft':
					setFocusedCol((c) => Math.max(0, c - 1));
					break;
				case 'ArrowRight':
					setFocusedCol((c) => Math.min(cols - 1, c + 1));
					break;
				case 'Home':
					if (e.ctrlKey || e.metaKey) setFocusedRow(0);
					setFocusedCol(0);
					break;
				case 'End':
					if (e.ctrlKey || e.metaKey) setFocusedRow(rowCount - 1);
					setFocusedCol(cols - 1);
					break;
				case 'PageUp':
					if (page > 1) fetchPage(page - 1);
					break;
				case 'PageDown':
					if (page < totalPages) fetchPage(page + 1);
					break;
				case 'e':
				case 'E':
					if (!editing) {
						setEditing(true);
					} else {
						setTimeout(() => {
							const input = focusedCellRef.current?.querySelector('input');
							input?.focus();
							input?.select();
						}, 0);
					}
					break;
				case 'Enter':
					if (editing) {
						setTimeout(() => {
							const input = focusedCellRef.current?.querySelector('input');
							input?.focus();
							input?.select();
						}, 0);
					} else {
						handled = false;
					}
					break;
				case 'x':
				case 'X':
				case 'Escape':
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
		document.addEventListener('keydown', handler, true);
		return () => document.removeEventListener('keydown', handler, true);
	}, [data, displayRows.length, page, totalPages, editing, onClose]);

	// Render into a portal at document.body so no ancestor's overflow,
	// transform, or stacking context can clip or hide the modal.
	return createPortal(
		<div
			style={{
				position: 'fixed',
				top: 0,
				left: 0,
				right: 0,
				bottom: 0,
				zIndex: 99999,
				background: 'rgba(0,0,0,0.78)',
				display: 'grid',
				placeItems: 'center',
				padding: 24,
			}}
			onClick={onClose}
		>
			<div
				style={{
					background: 'var(--lg-bg)',
					border: `2px solid ${editing ? 'var(--lg-coral)' : 'var(--lg-amber)'}`,
					boxShadow: '0 12px 40px rgba(0,0,0,0.65)',
					width: 'min(1200px, 92vw)',
					height: 'min(720px, 86vh)',
					minHeight: 320,
					display: 'flex',
					flexDirection: 'column',
					overflow: 'hidden',
					color: 'var(--lg-ink)',
				}}
				onClick={(e) => e.stopPropagation()}
			>
				{/* Header */}
				<div
					style={{
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						padding: '10px 14px',
						borderBottom: '1px solid var(--lg-border)',
						background: 'var(--lg-bg-2)',
					}}
				>
					<div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
						<IDisk size={10} />
						<span
							className="pixel"
							style={{ fontSize: 11, color: 'var(--lg-amber)', letterSpacing: '0.1em' }}
						>
							{tableName.toUpperCase()}
						</span>
						{editing && <span className="badge badge-warn">EDIT MODE</span>}
						{data && (
							<span className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-mute)' }}>
								{data.total_rows.toLocaleString()} rows · {data.columns.length} cols
							</span>
						)}
					</div>
					<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
						{editing ? (
							<>
								{dirty && (
									<button
										className="btn btn-primary"
										style={{ padding: '4px 10px', fontSize: 10 }}
										onClick={saveEdits}
										disabled={saving}
									>
										{saving ? 'SAVING…' : 'SAVE'}
									</button>
								)}
								<button
									className="btn btn-ghost"
									style={{ padding: '4px 10px', fontSize: 10 }}
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
								style={{ padding: '4px 10px', fontSize: 10 }}
								onClick={() => setEditing(true)}
							>
								EDIT
							</button>
						)}
						<button
							className="link"
							style={{ fontSize: 12, color: 'var(--lg-ink-mute)' }}
							onClick={onClose}
						>
							<IX size={10} /> CLOSE
						</button>
					</div>
				</div>

				{/* Table content */}
				<div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
					{loading ? (
						<div
							className="pixel"
							style={{
								fontSize: 11,
								color: 'var(--lg-amber)',
								letterSpacing: '0.1em',
								padding: 40,
								textAlign: 'center',
							}}
						>
							LOADING…
						</div>
					) : error ? (
						<div
							className="mono"
							style={{ fontSize: 11, color: 'var(--lg-coral)', padding: 40, textAlign: 'center' }}
						>
							{error}
						</div>
					) : data && displayRows.length > 0 ? (
						<table className="table" style={{ width: '100%' }}>
							<thead>
								<tr>
									<th
										style={{
											width: 50,
											fontFamily: 'var(--lg-pixel)',
											fontSize: 8,
											color: 'var(--lg-ink-mute)',
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
												background: isFocusedRow ? 'rgba(255, 191, 71, 0.08)' : undefined,
											}}
										>
											<td
												style={{
													fontFamily: 'var(--lg-mono)',
													fontSize: 9,
													color: isFocusedRow ? 'var(--lg-amber)' : 'var(--lg-ink-mute)',
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
															outline: '2px solid var(--lg-amber)',
															outlineOffset: -2,
															background: 'rgba(255, 191, 71, 0.15)',
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
																padding: '4px 6px',
																width: '100%',
																border: 'none',
																borderBottom: '1px solid var(--lg-border)',
																background: 'transparent',
															}}
															value={row[col] != null ? String(row[col]) : ''}
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
														{row[col] != null ? String(row[col]) : '—'}
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
							style={{
								fontSize: 11,
								color: 'var(--lg-ink-mute)',
								padding: 40,
								textAlign: 'center',
							}}
						>
							No data in this table.
						</div>
					)}
				</div>

				{/* Pagination footer */}
				<div
					style={{
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						padding: '8px 14px',
						borderTop: '1px solid var(--lg-border)',
						background: 'var(--lg-bg-2)',
					}}
				>
					<div
						className="mono"
						style={{
							fontSize: 10,
							color: 'var(--lg-ink-mute)',
							display: 'flex',
							flexDirection: 'column',
							gap: 2,
						}}
					>
						<div>
							PAGE {page} / {totalPages}
							{data && (
								<>
									{' · '}SHOWING {(page - 1) * 100 + 1}–{Math.min(page * 100, data.total_rows)} OF{' '}
									{data.total_rows.toLocaleString()}
								</>
							)}
						</div>
						<div style={{ fontSize: 9, color: 'var(--lg-ink-faint)' }}>
							<span style={{ color: 'var(--lg-amber)' }}>↑↓←→</span> NAV ·{' '}
							<span style={{ color: 'var(--lg-amber)' }}>E</span> EDIT ·{' '}
							<span style={{ color: 'var(--lg-amber)' }}>X</span>/
							<span style={{ color: 'var(--lg-amber)' }}>ESC</span> CLOSE ·{' '}
							<span style={{ color: 'var(--lg-amber)' }}>PGUP/PGDN</span> PAGE
						</div>
					</div>
					<div style={{ display: 'flex', gap: 6 }}>
						<button
							className="btn btn-ghost"
							style={{ padding: '4px 10px', fontSize: 10 }}
							disabled={page <= 1 || loading}
							onClick={() => fetchPage(1)}
						>
							«
						</button>
						<button
							className="btn btn-ghost"
							style={{ padding: '4px 10px', fontSize: 10 }}
							disabled={page <= 1 || loading}
							onClick={() => fetchPage(page - 1)}
						>
							‹ PREV
						</button>
						<button
							className="btn btn-ghost"
							style={{ padding: '4px 10px', fontSize: 10 }}
							disabled={page >= totalPages || loading}
							onClick={() => fetchPage(page + 1)}
						>
							NEXT ›
						</button>
						<button
							className="btn btn-ghost"
							style={{ padding: '4px 10px', fontSize: 10 }}
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
