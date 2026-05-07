import { useState, useEffect, useMemo, Fragment } from 'react';
import { IDisk } from '../icons';
import { usePipelineCtx } from './context';
import { ErpnextLiveExport } from './ErpnextExport';
import { FormatPicker } from './FormatPicker';

export function RlExport({ onDone }: { onDone: () => void }) {
	const { projectId, uploadResult, transformResult, loadResult, setLoadResult } = usePipelineCtx();
	// Strategy-driven formats (Frappe CSV, ERPnext live) always available
	// when the user has uploaded data — the backend re-runs transform on
	// demand if the heavy `transformed` payload was dropped between
	// sessions, so we don't gate the UI on `transformResult` being live.
	const usedStrategy = !!uploadResult;
	const [fmt, setFmt] = useState(usedStrategy ? 'frappe' : 'json');
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
	const totalRows =
		transformResult?.total_rows ?? visibleTables.reduce((a, t) => a + t.rowCount, 0) ?? 0;

	const FORMATS = usedStrategy
		? [
				{ id: 'erpnext', label: 'ERPNEXT (LIVE)', sub: 'Push directly via REST API' },
				{ id: 'frappe', label: 'FRAPPE CSV', sub: 'ERPnext Data Import (chunked, ordered)' },
				{ id: 'json', label: 'JSON', sub: 'One object per row' },
				{ id: 'csv', label: 'CSV', sub: 'One file per table' },
				{ id: 'sql', label: 'SQL', sub: 'CREATE + INSERT statements' },
			]
		: [
				{ id: 'json', label: 'JSON', sub: 'One object per row' },
				{ id: 'csv', label: 'CSV', sub: 'One file per table' },
				{ id: 'sql', label: 'SQL', sub: 'CREATE + INSERT statements' },
			];
	const runLoad = async () => {
		if (!uploadResult?.sessionId) return;
		setRunning(true);
		setError(null);
		try {
			const res = await fetch(`/api/load/${uploadResult.sessionId}`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
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
				throw new Error(err?.detail || 'Load failed');
			}
			const data = await res.json();
			setLoadResult(data);
		} catch (e) {
			setError(e instanceof Error ? e.message : 'Load failed');
		} finally {
			setRunning(false);
		}
	};

	if (fmt === 'erpnext') {
		return (
			<ErpnextLiveExport
				FORMATS={FORMATS}
				fmt={fmt}
				onFormatChange={(id) => {
					if (loadResult) setLoadResult(null);
					setFmt(id);
				}}
				sessionId={uploadResult?.sessionId ?? null}
				projectId={projectId}
				onDone={onDone}
			/>
		);
	}

	return (
		<div
			style={{
				display: 'grid',
				gridTemplateColumns: '240px 1fr 280px',
				gap: 14,
				marginTop: 14,
			}}
		>
			<FormatPicker
				formats={FORMATS}
				selected={fmt}
				onSelect={(id) => {
					if (loadResult) setLoadResult(null);
					setFmt(id);
				}}
			/>

			<div className="panel">
				<div className="panel-head">
					<span style={{ flex: 1 }}>{loadResult ? 'OUTPUT FILES' : 'EXPORT SETTINGS'}</span>
					<span className="badge badge-mute">{totalRows.toLocaleString()} ROWS</span>
				</div>
				<div className="panel-body">
					{loadResult ? (
						<div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
							{loadResult.output_files.length > 1 && (
								<a
									href={
										projectId
											? `/api/projects/${projectId}/download-all`
											: `/api/download-all/${uploadResult?.sessionId}`
									}
									download
									className="btn btn-primary"
									style={{
										justifyContent: 'center',
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
										href={
											projectId
												? `/api/projects/${projectId}/download/${file}`
												: `/api/download/${uploadResult?.sessionId}/${file}`
										}
										download
										className="btn btn-ghost"
										style={{ padding: '4px 10px', fontSize: 10 }}
									>
										DOWNLOAD
									</a>
								</div>
							))}
							{loadResult.exceptions_written && loadResult.exceptions_written.length > 0 && (
								<div
									style={{ marginTop: 12, paddingTop: 12, borderTop: '1px solid var(--lg-border)' }}
								>
									<div
										className="pixel"
										style={{ fontSize: 10, color: 'var(--lg-amber)', marginBottom: 8 }}
									>
										REVIEW NEEDED
									</div>
									{loadResult.exceptions_written.map((file) => (
										<div key={file} className="rl-file-row" style={{ marginTop: 4 }}>
											<span style={{ fontSize: 9, color: 'var(--lg-amber)' }}>⚠</span>
											<div style={{ flex: 1, fontSize: 12 }}>{file}</div>
											<a
												href={
													projectId
														? `/api/projects/${projectId}/download/${file}`
														: `/api/download/${uploadResult?.sessionId}/${file}`
												}
												download
												className="btn btn-ghost"
												style={{ padding: '4px 10px', fontSize: 10 }}
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
											style={{ fontSize: 10, color: 'var(--lg-coral)', marginTop: 4 }}
										>
											! {e}
										</div>
									))}
								</div>
							)}
							<div style={{ marginTop: 12 }}>
								<div
									className="pixel"
									style={{ fontSize: 10, color: 'var(--lg-ink-mute)', marginBottom: 8 }}
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
								color: 'var(--lg-ink-dim)',
								lineHeight: 1.7,
							}}
						>
							Select a format and click RUN to generate output files. The backend will process all
							transformed data and create downloadable {fmt.toUpperCase()} files.
						</div>
					)}
				</div>
			</div>

			<div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
				<div className="panel">
					<div className="panel-head">FINAL BOSS</div>
					<div className="panel-body">
						<div
							className="pixel glow-magenta"
							style={{ fontSize: 22, color: 'var(--lg-magenta)' }}
						>
							{totalRows.toLocaleString()}
						</div>
						<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-dim)' }}>
							{loadResult ? 'ROWS EXPORTED' : 'ROWS WILL MIGRATE'}
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
					<div className="mono" style={{ fontSize: 11, color: 'var(--lg-coral)' }}>
						{'> '}
						{error}
					</div>
				)}

				{!loadResult ? (
					<button
						className={`btn btn-primary ${!running ? 'pulse' : ''}`}
						onClick={runLoad}
						disabled={running || !uploadResult?.sessionId}
						style={{ fontSize: 13, padding: '12px 14px', justifyContent: 'center' }}
					>
						{running ? 'EXPORTING…' : '▶ EXPORT'}
					</button>
				) : (
					<button
						className="btn btn-primary"
						onClick={async () => {
							if (uploadResult?.sessionId) {
								try {
									await fetch(`/api/stats/${uploadResult.sessionId}`);
								} catch {}
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
