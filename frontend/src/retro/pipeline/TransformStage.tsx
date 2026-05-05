import { useState, useEffect } from 'react';
import { IX } from '../icons';
import { usePipelineCtx } from './context';
import { ACTIVE_TRANSFORM_LS_PREFIX } from './helpers';
import type {
	StrategyDescriptor,
	StrategyConfigField,
	TransformResult,
	AuditCheck,
	StrategyStats,
} from './types';

export function RlTransform({ onNext }: { onNext: () => void }) {
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
				const res = await fetch('/api/strategies');
				if (!res.ok) throw new Error('strategies endpoint unavailable');
				const json = await res.json();
				if (cancelled) return;
				const list = (json.strategies ?? []) as StrategyDescriptor[];
				setStrategies(list);
			} catch (e) {
				if (!cancelled) setLoadErr(e instanceof Error ? e.message : 'load failed');
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
		setDraftConfig(pickedName === name ? config : smartDefaults(s.config_schema, projectName));
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
		const lsKey = ACTIVE_TRANSFORM_LS_PREFIX + (projectId ?? 'guest');
		try {
			localStorage.setItem(lsKey, JSON.stringify({ sessionId: uploadResult.sessionId, projectId }));
		} catch {}
		try {
			const sid = uploadResult.sessionId;
			const saveRes = await fetch(`/api/strategies/${sid}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ strategy_name: pickedName, config }),
			});
			if (!saveRes.ok) {
				const err = await saveRes.json().catch(() => null);
				throw new Error(err?.detail || 'Could not save strategy config');
			}
			const runRes = await fetch(`/api/transform/${sid}`);
			if (!runRes.ok) {
				const err = await runRes.json().catch(() => null);
				throw new Error(err?.detail || 'Transform failed');
			}
			const data = (await runRes.json()) as TransformResult;
			setResult(data);
			setTransformResult(data);
		} catch (e) {
			setRunErr(e instanceof Error ? e.message : 'Transform failed');
		} finally {
			try {
				localStorage.removeItem(lsKey);
			} catch {}
			setRunning(false);
		}
	};

	if (result) {
		return <TransformResultView result={result} onReRun={() => setResult(null)} onNext={onNext} />;
	}

	return (
		<div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
			<TransformHeader />

			{loadErr && <RlErrorPanel message={loadErr} />}

			{!strategies && !loadErr && (
				<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-dim)' }}>
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
						disabled={
							running || !uploadResult?.sessionId || !pickedName || missingFields.length > 0
						}
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
		'Reading legacy tables…',
		'Building items + barcodes…',
		'Resolving customers and suppliers…',
		'Walking chart of accounts…',
		'Aggregating sales invoices…',
		'Streaming output to disk…',
	];
	const [phase, setPhase] = useState(0);
	const [pulseOffset, setPulseOffset] = useState(0);
	useEffect(() => {
		const phaseTimer = window.setInterval(() => setPhase((p) => (p + 1) % PHASES.length), 2400);
		const pulseTimer = window.setInterval(() => setPulseOffset((o) => (o + 6) % 60), 60);
		return () => {
			window.clearInterval(phaseTimer);
			window.clearInterval(pulseTimer);
		};
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);
	return (
		<div className="panel" style={{ borderColor: 'var(--lg-magenta)' }}>
			<div className="panel-head">
				<span className="pixel glow-magenta" style={{ color: 'var(--lg-magenta)' }}>
					▣ TRANSFORM IN PROGRESS
				</span>
			</div>
			<div
				className="panel-body"
				style={{
					display: 'flex',
					flexDirection: 'column',
					alignItems: 'center',
					gap: 14,
					padding: '26px 20px',
				}}
			>
				<div className="sprite-disk" />
				<div
					className="pixel"
					style={{ fontSize: 13, color: 'var(--lg-magenta)', letterSpacing: '0.15em' }}
				>
					{PHASES[phase]}
				</div>
				<div
					style={{
						width: '100%',
						maxWidth: 380,
						height: 10,
						border: '1px solid var(--lg-border-br)',
						background: 'var(--lg-bg-2)',
						overflow: 'hidden',
						position: 'relative',
					}}
				>
					<div
						style={{
							position: 'absolute',
							top: 0,
							bottom: 0,
							left: `${pulseOffset - 30}%`,
							width: '30%',
							background: 'linear-gradient(90deg, transparent, var(--lg-magenta), transparent)',
							boxShadow: '0 0 12px rgba(176,102,255,0.6)',
						}}
					/>
				</div>
				<div
					className="mono"
					style={{
						fontSize: 10,
						color: 'var(--lg-ink-mute)',
						maxWidth: 380,
						lineHeight: 1.5,
						textAlign: 'center',
					}}
				>
					Output streams to disk during transform — peak memory stays bounded so large datasets
					don't OOM. Don't close this tab.
				</div>
			</div>
		</div>
	);
}

function TransformHeader() {
	return (
		<div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
			<div className="pixel glow-cyan" style={{ fontSize: 11, color: 'var(--lg-cyan)' }}>
				▣ TRANSFORM
			</div>
			<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-dim)' }}>
				— pick a strategy, set config, run —
			</div>
		</div>
	);
}

function RlErrorPanel({ message }: { message: string }) {
	return (
		<div className="panel" style={{ borderColor: 'var(--lg-coral)', padding: 12 }}>
			<div className="mono" style={{ fontSize: 11, color: 'var(--lg-coral)' }}>
				{message}
			</div>
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
		<div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
			<StrategyPickerHeader count={strategies.length} />
			<div
				style={{
					display: 'grid',
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
		<div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
			<div className="pixel glow-cyan" style={{ fontSize: 11, color: 'var(--lg-cyan)' }}>
				▣ CHOOSE YOUR STRATEGY
			</div>
			<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-dim)' }}>
				— each strategy converts your tables to a known target schema —
			</div>
			<div style={{ flex: 1 }} />
			<div
				className="pixel"
				style={{
					fontSize: 9,
					color: 'var(--lg-ink-mute)',
					letterSpacing: '0.15em',
					padding: '3px 8px',
					border: '1px solid var(--lg-border-br)',
				}}
			>
				{count} STRATEGY{count === 1 ? '' : 'S'}
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
	const tier = strategy.tier || '';
	return (
		<button
			onClick={onPick}
			className="btn"
			style={{
				position: 'relative',
				textAlign: 'left',
				padding: '14px 14px 12px',
				borderColor: active ? 'var(--lg-magenta)' : 'var(--lg-border-br)',
				background: active ? 'rgba(176,102,255,0.06)' : 'transparent',
				boxShadow: active ? '0 0 14px rgba(176,102,255,0.4)' : 'none',
				display: 'flex',
				flexDirection: 'column',
				gap: 10,
				textTransform: 'none',
				letterSpacing: 0,
				minHeight: 200,
			}}
		>
			{tier && <StrategyTierBadge tier={tier} active={active} />}
			<div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
				<StrategyPickIndicator active={active} />
				<div style={{ display: 'flex', flexDirection: 'column', gap: 2, flex: 1 }}>
					<div className="pixel glow-magenta" style={{ fontSize: 14, color: 'var(--lg-magenta)' }}>
						{strategy.label.toUpperCase()}
					</div>
					<div
						className="pixel"
						style={{ fontSize: 8, color: 'var(--lg-ink-mute)', letterSpacing: '0.15em' }}
					>
						{(strategy.kind || 'GENERIC').toUpperCase()}
					</div>
				</div>
			</div>
			<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-dim)', lineHeight: 1.5 }}>
				{strategy.description}
			</div>
			<StrategyStatRow stats={stats} active={active} />
			{active && (
				<div
					className="pixel"
					style={{
						alignSelf: 'flex-end',
						fontSize: 8,
						color: 'var(--lg-magenta)',
						letterSpacing: '0.2em',
					}}
				>
					· EQUIPPED
				</div>
			)}
		</button>
	);
}

function StrategyTierBadge({ tier, active }: { tier: string; active: boolean }) {
	const color = active ? 'var(--lg-magenta)' : 'var(--lg-border-br)';
	return (
		<div
			className="pixel"
			style={{
				position: 'absolute',
				top: 8,
				right: 8,
				fontSize: 9,
				color,
				border: `1px solid ${color}`,
				padding: '1px 6px',
				letterSpacing: '0.1em',
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
				display: 'inline-block',
				width: 14,
				height: 14,
				marginTop: 2,
				border: `1px solid ${active ? 'var(--lg-magenta)' : 'var(--lg-border-br)'}`,
				background: active ? 'var(--lg-magenta)' : 'transparent',
				flexShrink: 0,
			}}
		/>
	);
}

function StrategyStatRow({ stats, active }: { stats: StrategyStats; active: boolean }) {
	const valueColor = active ? 'var(--lg-magenta)' : 'var(--lg-ink)';
	return (
		<div
			style={{
				display: 'grid',
				gridTemplateColumns: 'repeat(4, 1fr)',
				gap: 4,
				borderTop: '1px solid var(--lg-border)',
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
		<div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
			<div
				className="pixel"
				style={{ fontSize: 8, color: 'var(--lg-ink-mute)', letterSpacing: '0.15em' }}
			>
				{label}
			</div>
			<div className="pixel" style={{ fontSize: 14, color: valueColor }}>
				{value ?? '—'}
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
		<div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
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
	const type = field.type ?? 'string';

	if (type === 'boolean') {
		return (
			<label
				className="mono"
				title={help}
				style={{
					display: 'flex',
					alignItems: 'center',
					gap: 10,
					fontSize: 12,
					color: 'var(--lg-ink)',
				}}
			>
				<input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />
				<span>
					{label}
					{required ? ' *' : ''}
				</span>
			</label>
		);
	}

	return (
		<label title={help} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
			<span
				className="pixel"
				style={{ fontSize: 9, color: 'var(--lg-ink-mute)', letterSpacing: '0.1em' }}
			>
				{label}
				{required ? ' *' : ''}
			</span>
			<input
				type={type === 'date' ? 'date' : type === 'number' ? 'number' : 'text'}
				className="mono"
				value={(value as string | number | undefined) ?? ''}
				onChange={(e) => {
					if (type === 'number') {
						const n = e.target.valueAsNumber;
						onChange(Number.isNaN(n) ? '' : n);
					} else {
						onChange(e.target.value);
					}
				}}
				style={{
					background: 'var(--lg-bg-2)',
					border: '1px solid var(--lg-border-br)',
					color: 'var(--lg-ink)',
					padding: '8px 10px',
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
				.join(' · ')
		: '—';
	return (
		<div
			style={{
				display: 'flex',
				justifyContent: 'space-between',
				alignItems: 'center',
				gap: 12,
				borderTop: '1px solid var(--lg-border)',
				paddingTop: 14,
				marginTop: 4,
			}}
		>
			<div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
				<div
					className="pixel"
					style={{ fontSize: 9, color: 'var(--lg-ink-mute)', letterSpacing: '0.15em' }}
				>
					EQUIPPED:
				</div>
				<div className="mono" style={{ fontSize: 12, color: 'var(--lg-ink)' }}>
					{picked ? summary : '— pick a strategy above —'}
				</div>
				{missingFields.length > 0 && (
					<div className="mono" style={{ fontSize: 10, color: 'var(--lg-coral)' }}>
						Missing: {missingFields.join(', ')}
					</div>
				)}
			</div>
			<div style={{ display: 'flex', gap: 8 }}>
				{picked && onEditConfig && (
					<button
						className="btn btn-ghost"
						onClick={onEditConfig}
						style={{ fontSize: 11, padding: '12px 16px' }}
					>
						EDIT CONFIG
					</button>
				)}
				<button
					className={`btn btn-primary ${!disabled ? 'pulse' : ''}`}
					disabled={disabled}
					onClick={onRun}
					style={{ fontSize: 12, padding: '12px 24px' }}
				>
					{running ? 'TRANSFORMING…' : '▶ TRANSFORM'}
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
			if (e.key === 'Escape') onCancel();
		};
		window.addEventListener('keydown', onKey);
		return () => window.removeEventListener('keydown', onKey);
	}, [onCancel]);

	return (
		<div
			style={{
				position: 'fixed',
				inset: 0,
				zIndex: 9999,
				background: 'rgba(0,0,0,0.75)',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				padding: 24,
			}}
			onClick={onCancel}
		>
			<div
				style={{
					background: 'var(--lg-bg)',
					border: '2px solid var(--lg-magenta)',
					width: 420,
					maxWidth: '92vw',
					maxHeight: '90vh',
					display: 'flex',
					flexDirection: 'column',
				}}
				onClick={(e) => e.stopPropagation()}
			>
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
					<span
						className="pixel"
						style={{
							fontSize: 11,
							color: 'var(--lg-magenta)',
							letterSpacing: '0.1em',
						}}
					>
						{strategy.label.toUpperCase()}
					</span>
					<button
						className="btn btn-ghost"
						style={{ padding: '2px 6px', fontSize: 10 }}
						onClick={onCancel}
					>
						<IX size={10} />
					</button>
				</div>

				<div style={{ padding: '16px 14px', overflowY: 'auto' }}>
					{hasFields ? (
						<StrategyConfigForm
							schema={strategy.config_schema}
							value={config}
							onChange={onChange}
						/>
					) : (
						<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-dim)' }}>
							No configuration needed.
						</div>
					)}
				</div>

				<div
					style={{
						display: 'flex',
						justifyContent: 'flex-end',
						gap: 8,
						padding: '10px 14px',
						borderTop: '1px solid var(--lg-border)',
					}}
				>
					<button
						className="btn btn-ghost"
						style={{ padding: '6px 14px', fontSize: 11 }}
						onClick={onCancel}
					>
						CANCEL
					</button>
					<button
						className="btn btn-primary"
						style={{ padding: '6px 16px', fontSize: 11 }}
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
		<div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 14 }}>
			<div className="panel">
				<div className="panel-head">▼ TRANSFORM COMPLETE</div>
				<div className="panel-body" style={{ display: 'flex', gap: 24, alignItems: 'center' }}>
					<TransformBigStat label="ROWS" value={(result.total_rows ?? 0).toLocaleString()} />
					<TransformBigStat label="DOCTYPES" value={String(result.tables_transformed ?? 0)} />
					<div style={{ flex: 1 }} />
					<div
						className="mono"
						style={{ fontSize: 11, color: 'var(--lg-ink-dim)', maxWidth: 320, lineHeight: 1.5 }}
					>
						Strategy: <strong>{result.strategy_label || result.strategy_name || '—'}</strong>
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
						style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}
					>
						{docEntries.map(([name, count]) => (
							<div
								key={name}
								className="mono"
								style={{
									display: 'flex',
									justifyContent: 'space-between',
									gap: 12,
									padding: '6px 10px',
									border: '1px solid var(--lg-border)',
									fontSize: 11,
								}}
							>
								<span style={{ color: 'var(--lg-ink)' }}>{name}</span>
								<span style={{ color: 'var(--lg-magenta)', fontVariantNumeric: 'tabular-nums' }}>
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
					<div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
						{audit.preserved.map((c) => (
							<AuditRow key={c.label} check={c} />
						))}
					</div>
				</div>
			)}

			{result.warnings && result.warnings.length > 0 && (
				<div className="panel" style={{ borderColor: 'var(--lg-amber)' }}>
					<div className="panel-head">WARNINGS ({result.warnings.length})</div>
					<div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
						{result.warnings.map((w, i) => (
							<div key={i} className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-dim)' }}>
								— {w}
							</div>
						))}
					</div>
				</div>
			)}

			{result.setup_checklist_md && <SetupChecklistPanel md={result.setup_checklist_md} />}

			<div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
				<button className="btn btn-ghost" onClick={onReRun}>
					RE-RUN
				</button>
				<button className="btn btn-primary pulse" onClick={onNext}>
					▶ EXPORT
				</button>
			</div>
		</div>
	);
}

function TransformBigStat({ label, value }: { label: string; value: string }) {
	return (
		<div>
			<div
				className="pixel"
				style={{
					fontSize: 8,
					color: 'var(--lg-ink-mute)',
					letterSpacing: '0.15em',
					marginBottom: 4,
				}}
			>
				{label}
			</div>
			<div className="pixel glow-magenta" style={{ fontSize: 22, color: 'var(--lg-magenta)' }}>
				{value}
			</div>
		</div>
	);
}

function AuditRow({ check }: { check: AuditCheck }) {
	const okColor = 'var(--lg-cyan)';
	const failColor = 'var(--lg-coral)';
	const warnColor = 'var(--lg-magenta)';
	const tone =
		check.status === 'ok'
			? { dot: okColor, label: 'OK' }
			: check.status === 'short'
				? { dot: failColor, label: check.status.toUpperCase() }
				: { dot: warnColor, label: check.status.toUpperCase() };
	return (
		<div className="mono" style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11 }}>
			<span
				style={{
					display: 'inline-block',
					minWidth: 44,
					textAlign: 'center',
					padding: '1px 6px',
					border: `1px solid ${tone.dot}`,
					color: tone.dot,
					fontSize: 9,
					letterSpacing: '0.1em',
				}}
			>
				{tone.label}
			</span>
			<span style={{ flex: 1, color: 'var(--lg-ink)' }}>{check.label}</span>
			<span style={{ color: 'var(--lg-ink-dim)', fontVariantNumeric: 'tabular-nums' }}>
				{check.expected.toLocaleString()} → {check.actual.toLocaleString()}
			</span>
			<span
				style={{
					color: tone.dot,
					fontVariantNumeric: 'tabular-nums',
					minWidth: 56,
					textAlign: 'right',
				}}
			>
				{check.diff >= 0 ? `+${check.diff}` : check.diff}
			</span>
		</div>
	);
}

function SetupChecklistPanel({ md }: { md: string }) {
	const [open, setOpen] = useState(false);
	return (
		<div className="panel">
			<div className="panel-head" style={{ display: 'flex', alignItems: 'center' }}>
				<span>MIGRATION SETUP CHECKLIST</span>
				<span style={{ flex: 1 }} />
				<button className="link" onClick={() => setOpen((v) => !v)}>
					{open ? 'hide' : 'show'} ↗
				</button>
			</div>
			{open && (
				<pre
					className="mono"
					style={{
						margin: 0,
						padding: 14,
						fontSize: 10,
						color: 'var(--lg-ink-dim)',
						whiteSpace: 'pre-wrap',
						maxHeight: 380,
						overflow: 'auto',
					}}
				>
					{md}
				</pre>
			)}
		</div>
	);
}

function defaultsForSchema(schema: Record<string, StrategyConfigField>): Record<string, unknown> {
	const out: Record<string, unknown> = {};
	for (const [key, f] of Object.entries(schema)) {
		if (f.default !== undefined) out[key] = f.default;
		else if (f.type === 'boolean') out[key] = false;
		else out[key] = '';
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
	if ('company_name' in schema && !out.company_name && projectName) {
		out.company_name = humanizeProjectName(projectName);
	}
	if ('company_abbr' in schema && !out.company_abbr && projectName) {
		out.company_abbr = abbrFromName(projectName);
	}
	if ('opening_date' in schema && !out.opening_date) {
		out.opening_date = new Date().toISOString().slice(0, 10);
	}
	return out;
}

function humanizeProjectName(raw: string): string {
	const cleaned = raw.replace(/[-_]+/g, ' ').trim();
	return cleaned
		.split(/\s+/)
		.map((w) => (w ? w[0].toUpperCase() + w.slice(1).toLowerCase() : w))
		.join(' ');
}

function abbrFromName(raw: string): string {
	const parts = raw.replace(/[-_]+/g, ' ').trim().split(/\s+/).filter(Boolean);
	if (parts.length === 0) return 'ALA';
	if (parts.length === 1) return parts[0].slice(0, 3).toUpperCase();
	return parts
		.map((p) => p[0])
		.join('')
		.slice(0, 4)
		.toUpperCase();
}

function requiredMissing(
	schema: Record<string, StrategyConfigField>,
	value: Record<string, unknown>,
): string[] {
	const missing: string[] = [];
	for (const [key, f] of Object.entries(schema)) {
		if (!f.required) continue;
		const v = value[key];
		if (v === undefined || v === null || v === '') missing.push(f.label ?? key);
	}
	return missing;
}
