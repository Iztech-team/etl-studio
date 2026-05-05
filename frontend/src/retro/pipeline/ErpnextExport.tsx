import { useState, useEffect, useRef, useMemo, Fragment, type CSSProperties } from 'react';
import { ICheck } from '../icons';
import { usePipelineCtx } from './context';
import { FormatPicker } from './FormatPicker';

type ErpnextEvent = {
	event: string;
	[key: string]: unknown;
};

export function ErpnextLiveExport({
	FORMATS,
	fmt,
	onFormatChange,
	sessionId,
	projectId,
	onDone,
}: {
	FORMATS: { id: string; label: string; sub: string }[];
	fmt: string;
	onFormatChange: (id: string) => void;
	sessionId: string | null;
	projectId: string | null;
	onDone: () => void;
}) {
	const { transformResult, setTransformResult } = usePipelineCtx();
	const expectedCounts = transformResult?.output_doctypes ?? {};
	const allDoctypes = useMemo(() => Object.keys(expectedCounts).sort(), [expectedCounts]);

	const [url, setUrl] = useState('');
	const [apiKey, setApiKey] = useState('');
	const [apiSecret, setApiSecret] = useState('');
	const [company, setCompany] = useState('');
	const [companyAbbr, setCompanyAbbr] = useState('');
	const [forceReupload, setForceReupload] = useState(false);
	const [autoContinue, setAutoContinue] = useState(false);
	const [skipFiles, setSkipFiles] = useState<Set<string>>(() => new Set());
	const [haltedFile, setHaltedFile] = useState<{
		file: string;
		doctype: string;
		reason: string;
	} | null>(null);
	const [running, setRunning] = useState(false);
	const [events, setEvents] = useState<ErpnextEvent[]>([]);
	const [error, setError] = useState<string | null>(null);
	const [loadingDoctypes, setLoadingDoctypes] = useState(false);
	const [selectedDoctypes, setSelectedDoctypes] = useState<Set<string>>(() => new Set(allDoctypes));
	const [importedDoctypes, setImportedDoctypes] = useState<Set<string>>(() => new Set());
	const abortRef = useRef<AbortController | null>(null);

	useEffect(() => {
		setSelectedDoctypes(new Set(allDoctypes));
	}, [allDoctypes]);

	useEffect(() => {
		if (!projectId) return;
		fetch(`/api/erpnext-credentials/${projectId}`)
			.then((r) => r.json())
			.then((d) => {
				const c = d?.credentials;
				if (!c) return;
				setUrl(c.url ?? '');
				setApiKey(c.api_key ?? '');
				setApiSecret(c.api_secret ?? '');
				setCompany(c.company ?? '');
				setCompanyAbbr(c.company_abbr ?? '');
			})
			.catch(() => {});
		fetch(`/api/erpnext-imports/${projectId}`)
			.then((r) => r.json())
			.then((d) => {
				const records = (d?.imports ?? {}) as Record<
					string,
					{ doctype: string; imported_count: number; completed_at: string }
				>;
				setImportedDoctypes(new Set(Object.values(records).map((r) => r.doctype)));
			})
			.catch(() => {});
	}, [projectId]);

	// Seed company / abbr from the session's transform-stage strategy
	// config so the user doesn't have to retype what they already picked.
	// Saved erpnext credentials win (set above) — this only fills blanks.
	useEffect(() => {
		if (!sessionId) return;
		fetch(`/api/strategies/${sessionId}`)
			.then((r) => r.json())
			.then((d) => {
				const cfg = (d?.config ?? {}) as Record<string, unknown>;
				if (typeof cfg.company_name === 'string') {
					setCompany((prev) => prev || (cfg.company_name as string));
				}
				if (typeof cfg.company_abbr === 'string') {
					setCompanyAbbr((prev) => prev || (cfg.company_abbr as string));
				}
			})
			.catch(() => {});
	}, [sessionId]);

	// Doctype list is derived from transformResult.output_doctypes. On a
	// freshly-reopened project the transformResult is null until the user
	// triggers it; do that lazily here so the selection panel populates
	// without making the user visit the Transform stage first.
	useEffect(() => {
		if (!sessionId) return;
		if (transformResult) return;
		let cancelled = false;
		setLoadingDoctypes(true);
		fetch(`/api/transform/${sessionId}`)
			.then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
			.then((data) => {
				if (cancelled) return;
				setTransformResult(data);
			})
			.catch((err) => {
				if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load doctypes');
			})
			.finally(() => {
				if (!cancelled) setLoadingDoctypes(false);
			});
		return () => {
			cancelled = true;
		};
	}, [sessionId, transformResult, setTransformResult]);

	const send = async (extraSkips: string[] = []) => {
		if (!sessionId || !url || !apiKey || !apiSecret) return;
		const isResume = extraSkips.length > 0;
		setRunning(true);
		setError(null);
		setHaltedFile(null);
		if (!isResume) {
			setEvents([]);
			setSkipFiles(new Set());
		}
		const skipsForThisRun = isResume ? Array.from(new Set([...skipFiles, ...extraSkips])) : [];
		const ctl = new AbortController();
		abortRef.current = ctl;
		try {
			const res = await fetch(`/api/load-erpnext/${sessionId}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					url,
					api_key: apiKey,
					api_secret: apiSecret,
					company,
					company_abbr: companyAbbr,
					force_reupload: forceReupload && !isResume,
					halt_on_failure: !autoContinue,
					selected_doctypes: allDoctypes.length > 0 ? Array.from(selectedDoctypes) : null,
					skip_files: skipsForThisRun.length > 0 ? skipsForThisRun : null,
				}),
				signal: ctl.signal,
			});
			if (!res.ok || !res.body) {
				const e = await res.json().catch(() => null);
				throw new Error(e?.detail ?? `HTTP ${res.status}`);
			}
			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buf = '';
			while (true) {
				const { value, done } = await reader.read();
				if (done) break;
				buf += decoder.decode(value, { stream: true });
				let idx;
				while ((idx = buf.indexOf('\n\n')) >= 0) {
					const chunk = buf.slice(0, idx);
					buf = buf.slice(idx + 2);
					if (!chunk.startsWith('data: ')) continue;
					try {
						const ev = JSON.parse(chunk.slice(6)) as ErpnextEvent;
						setEvents((prev) => [...prev, ev]);
						if (ev.event === 'halted') {
							setHaltedFile({
								file: String(ev.file ?? ''),
								doctype: String(ev.doctype ?? ''),
								reason: String(ev.reason ?? 'failure'),
							});
						}
					} catch {}
				}
			}
		} catch (e) {
			if ((e as { name?: string })?.name !== 'AbortError') {
				setError(e instanceof Error ? e.message : 'Send failed');
			}
		} finally {
			setRunning(false);
			abortRef.current = null;
		}
	};

	const cancel = () => abortRef.current?.abort();
	const continueFromHalt = () => {
		if (!haltedFile) return;
		setSkipFiles((prev) => new Set([...prev, haltedFile.file]));
		send([haltedFile.file]);
	};
	const reset = () => {
		setEvents([]);
		setError(null);
		setHaltedFile(null);
		setSkipFiles(new Set());
		// Refresh the already-imported set since a successful run may
		// have just added entries to it.
		if (projectId) {
			fetch(`/api/erpnext-imports/${projectId}`)
				.then((r) => r.json())
				.then((d) => {
					const records = (d?.imports ?? {}) as Record<
						string,
						{ doctype: string; imported_count: number; completed_at: string }
					>;
					setImportedDoctypes(new Set(Object.values(records).map((r) => r.doctype)));
				})
				.catch(() => {});
		}
	};
	const toggleDoctype = (dt: string) =>
		setSelectedDoctypes((prev) => {
			const next = new Set(prev);
			if (next.has(dt)) next.delete(dt);
			else next.add(dt);
			return next;
		});
	const toggleAll = () =>
		setSelectedDoctypes((prev) =>
			prev.size === allDoctypes.length ? new Set() : new Set(allDoctypes),
		);

	const states = useMemo(
		() => deriveDoctypeStates(events, expectedCounts),
		[events, expectedCounts],
	);
	const idle = !running && events.length === 0;
	const complete = events.find((e) => e.event === 'complete');
	const fatalError = events.find((e) => e.event === 'error' && !e.file);

	return (
		<div
			style={{
				display: 'grid',
				gridTemplateColumns: '240px 1fr 280px',
				gap: 14,
				marginTop: 14,
			}}
		>
			<FormatPicker formats={FORMATS} selected={fmt} onSelect={onFormatChange} />

			<div className="panel">
				<div className="panel-head">ERPNEXT TARGET</div>
				<div className="panel-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
					<ErpnextField
						label="URL"
						value={url}
						onChange={setUrl}
						placeholder="https://erp.example.com"
						disabled={running}
					/>
					<ErpnextField label="API KEY" value={apiKey} onChange={setApiKey} disabled={running} />
					<ErpnextField
						label="API SECRET"
						value={apiSecret}
						onChange={setApiSecret}
						type="password"
						disabled={running}
					/>
					<ErpnextField
						label="COMPANY"
						value={company}
						onChange={setCompany}
						placeholder="Al Arabi"
						disabled={running}
					/>
					<ErpnextField
						label="ABBREVIATION"
						value={companyAbbr}
						onChange={setCompanyAbbr}
						placeholder="ALA"
						disabled={running}
					/>
					<label
						className="mono"
						style={{
							display: 'flex',
							alignItems: 'center',
							gap: 10,
							fontSize: 11,
							color: 'var(--lg-ink)',
							cursor: running ? 'not-allowed' : 'pointer',
						}}
						title="Re-send every CSV even if it was successfully imported on a previous run"
					>
						<input
							type="checkbox"
							checked={forceReupload}
							onChange={(e) => setForceReupload(e.target.checked)}
							disabled={running}
						/>
						<span>Re-upload everything</span>
					</label>
					<label
						className="mono"
						style={{
							display: 'flex',
							alignItems: 'center',
							gap: 10,
							fontSize: 11,
							color: 'var(--lg-ink)',
							cursor: running ? 'not-allowed' : 'pointer',
						}}
						title="By default the loader pauses on any partial / failed file and waits for you to click CONTINUE. Tick this to plough through automatically, logging errors as they happen."
					>
						<input
							type="checkbox"
							checked={autoContinue}
							onChange={(e) => setAutoContinue(e.target.checked)}
							disabled={running}
						/>
						<span>Auto-continue past failures</span>
					</label>
					{loadingDoctypes && allDoctypes.length === 0 && (
						<div
							className="mono"
							style={{
								borderTop: '1px solid var(--lg-border)',
								paddingTop: 12,
								marginTop: 4,
								fontSize: 11,
								color: 'var(--lg-ink-dim)',
							}}
						>
							Loading doctypes from transform…
						</div>
					)}
					{!loadingDoctypes && allDoctypes.length === 0 && (
						<div
							className="mono"
							style={{
								borderTop: '1px solid var(--lg-border)',
								paddingTop: 12,
								marginTop: 4,
								fontSize: 11,
								color: 'var(--lg-amber)',
							}}
						>
							No doctypes available — go back to Transform and run a strategy first.
						</div>
					)}
					{allDoctypes.length > 0 && (
						<div
							style={{
								borderTop: '1px solid var(--lg-border)',
								paddingTop: 12,
								marginTop: 4,
								display: 'flex',
								flexDirection: 'column',
								gap: 8,
							}}
						>
							<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
								<span
									className="pixel"
									style={{
										fontSize: 9,
										color: 'var(--lg-ink-mute)',
										letterSpacing: '0.1em',
										flex: 1,
									}}
								>
									{idle
										? `DOCTYPES — ${selectedDoctypes.size} of ${allDoctypes.length} selected`
										: `PROGRESS — ${
												states.filter((s) => s.status === 'success' || s.status === 'partial')
													.length
											} of ${
												states.filter((s) => s.status !== 'skipped' && s.status !== 'idle')
													.length || allDoctypes.length
											} done`}
								</span>
								{idle && (
									<button
										className="btn btn-ghost"
										onClick={toggleAll}
										style={{ padding: '2px 8px', fontSize: 9 }}
									>
										{selectedDoctypes.size === allDoctypes.length ? 'DESELECT ALL' : 'SELECT ALL'}
									</button>
								)}
							</div>
							<div
								style={{
									display: 'flex',
									flexDirection: 'column',
									gap: 6,
									maxHeight: 400,
									overflowY: 'auto',
								}}
							>
								{states.map((s) => (
									<DoctypeRow
										key={s.doctype}
										state={s}
										picked={selectedDoctypes.has(s.doctype)}
										idle={idle}
										previouslyImported={idle && !forceReupload && importedDoctypes.has(s.doctype)}
										onToggle={() => toggleDoctype(s.doctype)}
									/>
								))}
							</div>
						</div>
					)}
					{error && (
						<div className="mono" style={{ fontSize: 10, color: 'var(--lg-coral)' }}>
							{'> '}
							{error}
						</div>
					)}
				</div>
			</div>

			<div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
				<div className="panel">
					<div className="panel-head">VERIFICATION</div>
					<div className="panel-body">
						{complete ? (
							<VerificationList complete={complete} />
						) : fatalError ? (
							<div className="mono" style={{ fontSize: 10, color: 'var(--lg-coral)' }}>
								{String(fatalError.message ?? 'failed')}
							</div>
						) : (
							<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-dim)' }}>
								Counts will appear here once import completes.
							</div>
						)}
					</div>
				</div>

				{running ? (
					<button
						className="btn btn-primary"
						onClick={cancel}
						style={{ fontSize: 13, padding: '12px 14px', justifyContent: 'center' }}
					>
						CANCEL
					</button>
				) : events.length === 0 ? (
					<button
						className={`btn btn-primary ${!running ? 'pulse' : ''}`}
						onClick={() => send()}
						disabled={
							!sessionId ||
							!url ||
							!apiKey ||
							!apiSecret ||
							(allDoctypes.length > 0 && selectedDoctypes.size === 0)
						}
						style={{ fontSize: 13, padding: '12px 14px', justifyContent: 'center' }}
					>
						▶ SEND TO ERPNEXT
					</button>
				) : haltedFile ? (
					<div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
						<div
							className="mono"
							style={{
								fontSize: 10,
								color: 'var(--lg-amber)',
								padding: '8px 10px',
								border: '1px solid var(--lg-amber)',
								background: 'rgba(199,155,0,0.08)',
								lineHeight: 1.5,
							}}
						>
							{'▼ '}HALTED on {haltedFile.doctype || haltedFile.file} ({haltedFile.reason}). Click
							CONTINUE to skip this file and resume from the next one.
						</div>
						<button
							className="btn btn-primary pulse"
							onClick={continueFromHalt}
							style={{ fontSize: 13, padding: '12px 14px', justifyContent: 'center' }}
						>
							▶ CONTINUE — SKIP &amp; RESUME
						</button>
						<button
							className="btn btn-ghost"
							onClick={reset}
							style={{ fontSize: 11, padding: '10px 14px', justifyContent: 'center' }}
						>
							RESET — PICK AGAIN
						</button>
					</div>
				) : (
					<div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
						<button
							className="btn btn-ghost"
							onClick={reset}
							style={{ fontSize: 11, padding: '10px 14px', justifyContent: 'center' }}
						>
							RESET — PICK AGAIN
						</button>
						<button
							className="btn btn-primary"
							onClick={onDone}
							style={{ fontSize: 13, padding: '12px 14px', justifyContent: 'center' }}
						>
							{complete ? 'DONE · BACK TO PROJECTS' : 'BACK TO PROJECTS'}
						</button>
					</div>
				)}
			</div>
		</div>
	);
}

function ErpnextField({
	label,
	value,
	onChange,
	placeholder,
	type = 'text',
	disabled,
}: {
	label: string;
	value: string;
	onChange: (v: string) => void;
	placeholder?: string;
	type?: string;
	disabled?: boolean;
}) {
	return (
		<label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
			<span
				className="pixel"
				style={{ fontSize: 9, color: 'var(--lg-ink-mute)', letterSpacing: '0.1em' }}
			>
				{label}
			</span>
			<input
				type={type}
				className="mono"
				value={value}
				onChange={(e) => onChange(e.target.value)}
				placeholder={placeholder}
				disabled={disabled}
				autoComplete="off"
				spellCheck={false}
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

type DoctypeStatus =
	| 'idle'
	| 'settling'
	| 'queued'
	| 'uploading'
	| 'running'
	| 'success'
	| 'partial'
	| 'skipped'
	| 'error';

type DoctypeState = {
	doctype: string;
	expected: number;
	status: DoctypeStatus;
	imported: number;
	failed: number;
	warnings: string[];
	errors: string[];
	detail: string;
};

function deriveDoctypeStates(
	events: ErpnextEvent[],
	expected: Record<string, number>,
): DoctypeState[] {
	const map = new Map<string, DoctypeState>();
	for (const dt of Object.keys(expected)) {
		map.set(dt, {
			doctype: dt,
			expected: expected[dt],
			status: 'idle',
			imported: 0,
			failed: 0,
			warnings: [],
			errors: [],
			detail: '',
		});
	}
	for (const ev of events) {
		const dt = (ev.doctype as string | undefined) ?? '';
		if (!dt) continue;
		const s = map.get(dt) ?? {
			doctype: dt,
			expected: 0,
			status: 'idle' as DoctypeStatus,
			imported: 0,
			failed: 0,
			warnings: [],
			errors: [],
			detail: '',
		};
		switch (ev.event) {
			case 'settling':
				// Backend sleeps a few seconds between files so Frappe can
				// commit the previous import before this one reads it.
				// Stamp the next doctype row with a 'settling' state so
				// the user sees we're not hung — just waiting.
				if (s.status === 'idle') {
					s.status = 'settling';
					const delay = (ev.delay as number | undefined) ?? 0;
					s.detail = delay > 0 ? `settling ${delay}s…` : 'settling…';
				}
				break;
			case 'uploading':
				s.status = 'uploading';
				s.detail = (ev.stage as string) ?? 'uploading';
				break;
			case 'queued':
				s.status = 'queued';
				s.detail = 'queued in Frappe';
				break;
			case 'polling': {
				s.status = 'running';
				s.imported = (ev.imported as number) ?? s.imported;
				s.failed = (ev.failed as number) ?? s.failed;
				const status = (ev.status as string | undefined) ?? 'in progress';
				s.detail = status.toLowerCase();
				if (Array.isArray(ev.warnings)) s.warnings = ev.warnings as string[];
				break;
			}
			case 'done': {
				const finalStatus = (ev.status as string | undefined) ?? 'success';
				s.status = finalStatus === 'success' ? 'success' : 'partial';
				s.imported = (ev.imported as number) ?? s.imported;
				s.failed = (ev.failed as number) ?? s.failed;
				if (Array.isArray(ev.warnings)) s.warnings = ev.warnings as string[];
				if (Array.isArray(ev.errors)) s.errors = ev.errors as string[];
				s.detail = finalStatus;
				break;
			}
			case 'skipped':
				// Don't overwrite a previously-resolved status — a
				// follow-up run that user-skips this file shouldn't
				// erase the original partial / error display.
				if (s.status === 'idle') {
					s.status = 'skipped';
					s.detail = (ev.reason as string) ?? 'skipped';
					if (typeof ev.imported === 'number') s.imported = ev.imported as number;
				}
				break;
			case 'error':
				s.status = 'error';
				s.detail = (ev.message as string) ?? 'failed';
				break;
		}
		map.set(dt, s);
	}
	return Array.from(map.values());
}

const STATUS_COLOR: Record<DoctypeStatus, string> = {
	idle: 'var(--lg-ink-mute)',
	settling: 'var(--lg-ink-dim)',
	queued: 'var(--lg-amber)',
	uploading: 'var(--lg-amber)',
	running: 'var(--lg-cyan)',
	success: 'var(--lg-magenta)',
	partial: 'var(--lg-amber)',
	skipped: 'var(--lg-ink-dim)',
	error: 'var(--lg-coral)',
};

function barFill(state: DoctypeState, color: string): CSSProperties {
	const pct = state.expected > 0 ? Math.min(100, (state.imported / state.expected) * 100) : 0;
	const isActive =
		state.status === 'uploading' || state.status === 'queued' || state.status === 'running';

	if (state.status === 'success') {
		return { width: '100%', background: color };
	}
	if (state.status === 'skipped') {
		return { width: '100%', background: color, opacity: 0.5 };
	}
	if (state.status === 'error') {
		return { width: '100%', background: color };
	}
	if (state.status === 'partial') {
		return {
			width: `${Math.max(pct, 5)}%`,
			background: color,
		};
	}
	if (state.status === 'settling') {
		// Slim, dim, slow-pulsing bar — distinct from the active stripe-march.
		return {
			width: '12%',
			background: color,
			opacity: 0.6,
			animation: 'rl-bug-glow 1.4s ease-in-out infinite',
		};
	}
	if (isActive) {
		return {
			width: `${Math.max(pct, 8)}%`,
			background: `repeating-linear-gradient(45deg, ${color}, ${color} 6px, rgba(255,255,255,0.18) 6px, rgba(255,255,255,0.18) 12px)`,
			backgroundSize: '24px 24px',
			animation: 'rl-stripe-march .8s linear infinite',
		};
	}
	// idle
	return { width: '0%', background: color };
}

function DoctypeRow({
	state,
	picked,
	idle,
	previouslyImported,
	onToggle,
}: {
	state: DoctypeState;
	picked: boolean;
	idle: boolean;
	previouslyImported: boolean;
	onToggle: () => void;
}) {
	const color = STATUS_COLOR[state.status];
	const isActive =
		state.status === 'uploading' || state.status === 'queued' || state.status === 'running';
	const dimmed = idle && !picked;
	const fill = barFill(state, color);

	return (
		<div
			onClick={idle ? onToggle : undefined}
			style={{
				border: `1px solid ${idle && picked ? 'var(--lg-amber)' : 'var(--lg-border)'}`,
				background: isActive
					? 'rgba(80,180,220,0.05)'
					: state.status === 'success'
						? 'rgba(140,200,120,0.05)'
						: state.status === 'error'
							? 'rgba(220,90,90,0.05)'
							: 'transparent',
				padding: '8px 10px',
				display: 'flex',
				flexDirection: 'column',
				gap: 6,
				cursor: idle ? 'pointer' : 'default',
				opacity: dimmed ? 0.5 : 1,
				animation: 'rl-row-in .2s ease-out both',
			}}
		>
			<div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
				{idle ? (
					<span
						style={{
							display: 'inline-flex',
							alignItems: 'center',
							justifyContent: 'center',
							width: 12,
							height: 12,
							border: '1px solid var(--lg-amber)',
							background: picked ? 'var(--lg-amber)' : 'transparent',
							color: '#0a0410',
							flexShrink: 0,
						}}
					>
						{picked && <ICheck size={6} />}
					</span>
				) : (
					<span
						style={{
							display: 'inline-block',
							width: 8,
							height: 8,
							borderRadius: '50%',
							background: color,
							animation: isActive ? 'rl-pulse 1.1s ease-in-out infinite' : 'none',
							flexShrink: 0,
						}}
					/>
				)}
				<span
					className="pixel"
					style={{
						fontSize: 11,
						color: 'var(--lg-ink)',
						letterSpacing: '0.05em',
						flex: 1,
					}}
				>
					{state.doctype.toUpperCase()}
				</span>
				{previouslyImported && (
					<span
						className="mono"
						title="A previous run already imported this doctype — it will be auto-skipped unless 'Re-upload everything' is checked."
						style={{
							fontSize: 9,
							color: 'var(--lg-green)',
							border: '1px solid var(--lg-green)',
							padding: '1px 6px',
							letterSpacing: '0.1em',
							flexShrink: 0,
						}}
					>
						✓ ALREADY IMPORTED
					</span>
				)}
				<span className="mono" style={{ fontSize: 10, color, fontVariantNumeric: 'tabular-nums' }}>
					{state.status === 'idle'
						? `${state.expected.toLocaleString()} rows`
						: state.status === 'settling'
							? state.detail
							: state.expected > 0
								? `${state.imported}/${state.expected}`
								: state.imported > 0
									? `${state.imported}`
									: state.detail}
					{state.failed > 0 && (
						<span style={{ color: 'var(--lg-coral)' }}> · {state.failed} failed</span>
					)}
				</span>
			</div>
			{!idle && (
				<div
					style={{
						height: 6,
						background: 'var(--lg-bg-2)',
						border: '1px solid var(--lg-border)',
						position: 'relative',
						overflow: 'hidden',
					}}
				>
					<div
						style={{
							height: '100%',
							transition: 'width .25s ease-out',
							...fill,
						}}
					/>
				</div>
			)}
			{!idle && state.detail && state.status !== 'running' && (
				<span
					className="mono"
					style={{ fontSize: 9, color: 'var(--lg-ink-dim)', letterSpacing: '0.05em' }}
				>
					{state.detail}
				</span>
			)}
			{state.warnings.slice(0, 3).map((w, i) => (
				<span key={`w${i}`} style={{ color: 'var(--lg-amber)', fontSize: 9, paddingLeft: 16 }}>
					⚠ {w}
				</span>
			))}
			{state.errors.slice(0, 3).map((e, i) => (
				<span key={`e${i}`} style={{ color: 'var(--lg-coral)', fontSize: 9, paddingLeft: 16 }}>
					✗ {e}
				</span>
			))}
			{(state.warnings.length > 3 || state.errors.length > 3) && (
				<span style={{ color: 'var(--lg-ink-mute)', fontSize: 9, paddingLeft: 16 }}>
					+ {state.warnings.length + state.errors.length - 3} more
				</span>
			)}
		</div>
	);
}

function EventRow({ ev }: { ev: ErpnextEvent }) {
	const file = (ev.file as string | undefined) ?? '';
	const doctype = (ev.doctype as string | undefined) ?? '';
	const stage = (ev.stage as string | undefined) ?? '';
	const status = (ev.status as string | undefined) ?? '';
	const message = (ev.message as string | undefined) ?? '';
	const reason = (ev.reason as string | undefined) ?? '';
	const imported = (ev.imported as number | undefined) ?? null;
	const failed = (ev.failed as number | undefined) ?? null;
	const warnings = (ev.warnings as string[] | undefined) ?? [];
	const errors = (ev.errors as string[] | undefined) ?? [];

	const palette: Record<string, string> = {
		begin: 'var(--lg-cyan)',
		stage: 'var(--lg-cyan)',
		preflight: 'var(--lg-ink-mute)',
		settling: 'var(--lg-ink-dim)',
		uploading: 'var(--lg-amber)',
		queued: 'var(--lg-amber)',
		polling: 'var(--lg-cyan)',
		done: 'var(--lg-green)',
		skipped: 'var(--lg-amber)',
		error: 'var(--lg-coral)',
		complete: 'var(--lg-green)',
	};
	const color = palette[ev.event] ?? 'var(--lg-ink-mute)';

	let label = ev.event.toUpperCase();
	if (ev.event === 'polling' && status) label = status.toUpperCase();
	if (file) label += ` · ${file}`;
	else if (stage) label += ` · ${stage}`;
	else if (doctype) label += ` · ${doctype}`;

	const parts: string[] = [];
	if (imported !== null) {
		parts.push(`${imported} imported${failed ? `, ${failed} failed` : ''}`);
	}
	if (reason) parts.push(reason);
	else if (message) parts.push(message);

	return (
		<div
			className="mono"
			style={{ fontSize: 10, display: 'flex', flexDirection: 'column', gap: 2, lineHeight: 1.6 }}
		>
			<div style={{ display: 'flex', gap: 8 }}>
				<span className="pixel" style={{ color, letterSpacing: '0.1em', flexShrink: 0 }}>
					{label}
				</span>
				{parts.length > 0 && (
					<span style={{ color: 'var(--lg-ink-dim)' }}>— {parts.join(' · ')}</span>
				)}
			</div>
			{warnings.map((w, i) => (
				<div key={`w${i}`} style={{ color: 'var(--lg-amber)', fontSize: 9, paddingLeft: 16 }}>
					⚠ {w}
				</div>
			))}
			{errors.map((e, i) => (
				<div key={`e${i}`} style={{ color: 'var(--lg-coral)', fontSize: 9, paddingLeft: 16 }}>
					✗ {e}
				</div>
			))}
		</div>
	);
}

function VerificationList({ complete }: { complete: ErpnextEvent }) {
	const verification =
		(complete.verification as Record<
			string,
			{
				expected: number;
				actual: number | null;
				error?: string;
			}
		>) ?? {};
	const entries = Object.entries(verification);
	if (entries.length === 0) {
		return (
			<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-dim)' }}>
				No doctypes to verify.
			</div>
		);
	}
	return (
		<dl className="kv">
			{entries.map(([dt, v]) => {
				const ok = v.actual !== null && v.actual >= v.expected;
				return (
					<Fragment key={dt}>
						<dt>{dt.toUpperCase()}</dt>
						<dd
							style={{
								color: v.error ? 'var(--lg-coral)' : ok ? 'var(--lg-green)' : 'var(--lg-amber)',
							}}
						>
							{v.error ? 'err' : `${v.actual ?? '?'}/${v.expected}`}
						</dd>
					</Fragment>
				);
			})}
		</dl>
	);
}

// EventRow is defined for potential future use in an event log panel
export { EventRow };
