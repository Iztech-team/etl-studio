import { useState, useEffect, useMemo, type ReactNode } from 'react';
import { IArrow, ICheck } from '../icons';
import { usePipelineCtx } from './context';
import type { EntityDescriptor } from './types';

export function RlExtract({ onNext }: { onNext: () => void }) {
	const { uploadResult, setUploadResult, setTransformResult, setLoadResult } = usePipelineCtx();
	const [entities, setEntities] = useState<EntityDescriptor[] | null>(null);
	const [picks, setPicks] = useState<Set<string>>(new Set());
	const [saving, setSaving] = useState(false);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		fetch('/api/entities')
			.then((r) => r.json())
			.then((d) => {
				if (cancelled) return;
				const list = (d.entities ?? []) as EntityDescriptor[];
				setEntities(list);
				const prev = uploadResult?.selectedEntities ?? [];
				setPicks(prev.length > 0 ? new Set(prev) : new Set(list.map((e) => e.id)));
			})
			.catch((e) => {
				if (!cancelled) setError(String(e));
			});
		return () => {
			cancelled = true;
		};
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
			<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-dim)', padding: 24 }}>
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
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ entities: Array.from(picks) }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				throw new Error(err?.detail ?? 'Selection failed');
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
			setError(e instanceof Error ? e.message : 'Selection failed');
		} finally {
			setSaving(false);
		}
	};

	return (
		<div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
			<div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
				<div className="pixel glow-amber" style={{ fontSize: 11, color: 'var(--lg-amber)' }}>
					▣ EXTRACT — pick what to migrate
				</div>
				<div style={{ flex: 1 }} />
				<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-dim)' }}>
					{effective.size} of {entities.length} selected
				</div>
			</div>

			<div
				style={{
					display: 'grid',
					gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
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
				<div className="mono" style={{ fontSize: 11, color: 'var(--lg-coral)' }}>
					{'> '}
					{error}
				</div>
			)}

			<div style={{ display: 'flex', justifyContent: 'flex-end' }}>
				<button
					className="btn btn-primary"
					onClick={proceed}
					disabled={effective.size === 0 || saving || !uploadResult?.sessionId}
				>
					{saving ? 'SAVING…' : 'CONTINUE TO TRANSFORM'} <IArrow size={10} />
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
			title={forced ? 'Auto-included as a dependency' : ''}
			style={{
				textAlign: 'left',
				padding: '12px 14px',
				borderColor: active ? 'var(--lg-amber)' : 'var(--lg-border-br)',
				background: forced
					? 'rgba(199,155,0,0.04)'
					: picked
						? 'rgba(199,155,0,0.08)'
						: 'transparent',
				opacity: forced ? 0.7 : 1,
				cursor: forced ? 'not-allowed' : 'pointer',
				display: 'flex',
				flexDirection: 'column',
				gap: 6,
				textTransform: 'none',
				letterSpacing: 0,
			}}
		>
			<div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
				<span
					style={{
						display: 'inline-flex',
						alignItems: 'center',
						justifyContent: 'center',
						width: 14,
						height: 14,
						border: '1px solid var(--lg-amber)',
						background: active ? 'var(--lg-amber)' : 'transparent',
						color: '#0a0410',
						flexShrink: 0,
					}}
				>
					{active && <ICheck size={8} />}
				</span>
				<span
					className="pixel"
					style={{
						fontSize: 12,
						color: active ? 'var(--lg-amber)' : 'var(--lg-ink)',
						letterSpacing: '0.05em',
					}}
				>
					{entity.label.toUpperCase()}
				</span>
			</div>
			{forced ? (
				<span className="mono" style={{ fontSize: 9, color: 'var(--lg-ink-mute)' }}>
					auto-included
				</span>
			) : depLabels.length > 0 ? (
				<span className="mono" style={{ fontSize: 9, color: 'var(--lg-ink-dim)' }}>
					requires: {depLabels.join(', ')}
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
export function RlTableSidebar({
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
		setNames: (updater: (prev: Record<string, string>) => Record<string, string>) => void;
		renaming: string | null;
		setRenaming: (n: string | null) => void;
	};
	badge?: (name: string) => ReactNode;
}) {
	const [search, setSearch] = useState('');
	const filtered = useMemo(() => {
		const q = search.trim().toLowerCase();
		if (!q) return tables;
		return tables.filter((t) => t.name.toLowerCase().includes(q));
	}, [tables, search]);

	return (
		<div
			className="panel"
			style={{
				display: 'flex',
				flexDirection: 'column',
				maxHeight: 'calc(100vh - 220px)',
				minHeight: 320,
			}}
		>
			<div className="panel-head">TABLES · {tables.length}</div>
			<div
				style={{
					padding: '8px 10px',
					borderBottom: '1px solid var(--lg-border)',
					background: 'var(--lg-bg-2)',
				}}
			>
				<input
					placeholder="Search tables…"
					value={search}
					onChange={(e) => setSearch(e.target.value)}
					style={{
						width: '100%',
						fontSize: 11,
						padding: '5px 8px',
						background: 'var(--lg-bg)',
						border: '1px solid var(--lg-border)',
						color: 'var(--lg-ink)',
						fontFamily: 'var(--lg-mono)',
						textTransform: 'none',
						letterSpacing: 0,
						outline: 'none',
					}}
				/>
			</div>
			<div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
				{filtered.length === 0 ? (
					<div
						className="mono"
						style={{
							fontSize: 11,
							color: 'var(--lg-ink-mute)',
							padding: 14,
							textAlign: 'center',
						}}
					>
						No matches.
					</div>
				) : (
					filtered.map((t) => {
						const active = t.name === activeTable;
						const renamed = rename && rename.names[t.name] && rename.names[t.name] !== t.name;
						const isRenaming = rename?.renaming === t.name;
						return (
							<div
								key={t.name}
								onClick={() => onPick(t.name)}
								style={{
									display: 'flex',
									alignItems: 'center',
									gap: 6,
									padding: '6px 10px',
									cursor: 'pointer',
									background: active ? 'var(--lg-amber)' : 'transparent',
									color: active ? '#0a0410' : 'var(--lg-ink)',
									borderBottom: '1px solid var(--lg-border)',
									fontFamily: 'var(--lg-pixel)',
									fontSize: 9,
									letterSpacing: '0.08em',
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
											if (e.key === 'Enter') rename.setRenaming(null);
											if (e.key === 'Escape') {
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
											padding: '2px 6px',
											fontSize: 10,
											background: 'var(--lg-bg)',
											border: '1px solid var(--lg-border)',
											color: 'var(--lg-ink)',
											fontFamily: 'var(--lg-mono)',
											textTransform: 'none',
											letterSpacing: 0,
										}}
									/>
								) : (
									<>
										<div
											style={{
												flex: 1,
												overflow: 'hidden',
												textOverflow: 'ellipsis',
												whiteSpace: 'nowrap',
											}}
											title={t.name}
										>
											{renamed ? (
												<>
													<span
														style={{
															opacity: 0.5,
															textDecoration: 'line-through',
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
												fontFamily: 'var(--lg-mono)',
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
													padding: '1px 5px',
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
