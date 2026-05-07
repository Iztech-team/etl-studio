import { useState, useRef, useEffect, type ChangeEvent, type DragEvent } from 'react';
import { IArrow, ICheck, IDisk, IUpload, IX } from '../icons';
import { usePipelineCtx } from './context';
import {
	detectKind,
	isDbFile,
	fmtSize,
	_isUploadingPhase,
	consumeExtractStream,
	uploadToBackend,
	donePayloadToUploadResult,
	ACCEPT,
	ACTIVE_EXTRACTION_LS_PREFIX,
} from './helpers';
import type { FileKind, StagedFile, UploadProgress, ExtractEvent } from './types';

function UploadProgressView({
	progress,
	fileCount,
}: {
	progress: UploadProgress;
	fileCount: number;
}) {
	const pct =
		progress.total > 0 ? Math.min(100, Math.floor((progress.loaded / progress.total) * 100)) : 0;
	return (
		<>
			<div
				className="pixel"
				style={{ fontSize: 14, color: 'var(--lg-amber)', letterSpacing: '0.15em' }}
			>
				UPLOADING…
			</div>
			<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-dim)' }}>
				{fileCount} FILE{fileCount === 1 ? '' : 'S'} · {fmtSize(progress.loaded)} /{' '}
				{progress.total > 0 ? fmtSize(progress.total) : '…'}
			</div>
			<div
				style={{
					width: '100%',
					maxWidth: 360,
					height: 12,
					marginTop: 6,
					border: '1px solid var(--lg-border-br)',
					background: 'var(--lg-bg-2)',
					position: 'relative',
					overflow: 'hidden',
				}}
			>
				<div
					style={{
						width: `${pct}%`,
						height: '100%',
						background: 'var(--lg-amber)',
						transition: 'width 120ms linear',
						boxShadow: '0 0 8px rgba(255,179,71,0.6)',
					}}
				/>
				<div
					className="pixel"
					style={{
						position: 'absolute',
						top: 0,
						left: 0,
						right: 0,
						bottom: 0,
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'center',
						fontSize: 9,
						color: pct > 50 ? '#1a1006' : 'var(--lg-ink)',
						mixBlendMode: pct > 50 ? 'normal' : 'normal',
						letterSpacing: '0.15em',
					}}
				>
					{pct}%
				</div>
			</div>
			<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-mute)', marginTop: 4 }}>
				Don't close this tab until the upload reaches 100%.
			</div>
		</>
	);
}

function kindBadge(kind: FileKind) {
	const label = kind.toUpperCase();
	const cls =
		kind === 'unknown'
			? 'badge badge-err'
			: kind === 'ib' || kind === 'sqlite'
				? 'badge badge-solid'
				: 'badge badge-ok';
	return <span className={cls}>{label}</span>;
}

const DEFAULT_IB_PASSWORDS = ['masterkey', 'AshSMSsw'];
const PASSWORDS_LS_KEY = 'etl_studio.ib_known_passwords';
const NO_PASSWORD = '__none__';

type ActiveExtraction = {
	sessionId: string;
	projectId: string | null;
	filename: string;
	startedAt: string;
};

function activeExtractionKey(projectId: string | null): string {
	return `${ACTIVE_EXTRACTION_LS_PREFIX}${projectId ?? 'guest'}`;
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
					if (typeof v === 'string' && v && !merged.includes(v)) merged.push(v);
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

export function RlUpload({ onNext }: { onNext: () => void }) {
	const { staged, addStaged, removeStaged, clearStaged, projectId, setUploadResult } =
		usePipelineCtx();
	const inputRef = useRef<HTMLInputElement | null>(null);
	const [uploading, setUploading] = useState(false);
	const [dragOver, setDragOver] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const [knownPasswords, setKnownPasswords] = useState<string[]>(() => loadKnownIbPasswords());
	const [selectedPassword, setSelectedPassword] = useState<string>(DEFAULT_IB_PASSWORDS[0]);
	const [addingNew, setAddingNew] = useState(false);
	const [newPassword, setNewPassword] = useState('');

	const [extractStatus, setExtractStatus] = useState<string>('');
	const [allTables, setAllTables] = useState<string[]>([]);
	const [doneTables, setDoneTables] = useState<{ name: string; rows: number }[]>([]);
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
		e.target.value = '';
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
			setNewPassword('');
			return;
		}
		if (!knownPasswords.includes(trimmed)) {
			const next = [...knownPasswords, trimmed];
			setKnownPasswords(next);
			saveKnownIbPasswords(next);
		}
		setSelectedPassword(trimmed);
		setNewPassword('');
		setAddingNew(false);
	};

	const handleEvent = (evt: ExtractEvent) => {
		if (evt.event === 'listing') {
			setExtractStatus('Listing tables…');
		} else if (evt.event === 'start') {
			setAllTables(evt.tables);
			setExtractStatus(`Extracting ${evt.tables.length} tables…`);
		} else if (evt.event === 'table_done') {
			setDoneTables((prev) => [...prev, { name: evt.name, rows: evt.rows }]);
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
		setExtractStatus('Uploading…');
		setAllTables([]);
		setDoneTables([]);
		setUploadProgress({ loaded: 0, total: 0 });
		const dbFile = staged.find((s) => isDbFile(s.file.name));
		try {
			const password = selectedPassword === NO_PASSWORD ? undefined : selectedPassword;
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
				(e instanceof DOMException && e.name === 'AbortError') ||
				(e instanceof Error && e.message.toLowerCase().includes('abort'));
			if (aborted) {
				setError(null);
				setExtractStatus('');
			} else {
				setError(e instanceof Error ? e.message : 'Upload failed');
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
		setExtractStatus('Cancelling…');
		const sid = sessionRef.current;
		abortRef.current.abort();
		if (sid) {
			void fetch(`/api/extract/${sid}/cancel`, { method: 'POST' }).catch(() => undefined);
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
				if (status.status !== 'extracting' && status.status !== 'done') {
					clearActiveExtraction(projectId);
					return;
				}
				if (cancelled) return;
				setUploading(true);
				setError(null);
				setExtractStatus(
					status.status === 'done'
						? 'Loading completed extraction…'
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
					setError(e instanceof Error ? e.message : 'Failed to resume extraction');
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
				display: 'grid',
				gridTemplateColumns: '1fr 320px',
				gap: 14,
				marginTop: 14,
			}}
		>
			<div className="panel">
				<div className="panel-head">
					<IUpload size={10} />{' '}
					{uploading
						? _isUploadingPhase(uploadProgress)
							? 'UPLOADING TO SERVER'
							: 'EXTRACTING DATABASE'
						: 'UPLOAD DATA FILES'}
				</div>
				<div className="panel-body">
					{uploading ? (
						<div
							style={{
								padding: '32px 20px',
								textAlign: 'center',
								display: 'flex',
								flexDirection: 'column',
								alignItems: 'center',
								gap: 12,
							}}
						>
							<div className="sprite-disk" style={{ margin: '0 auto 4px' }} />
							{_isUploadingPhase(uploadProgress) ? (
								<UploadProgressView progress={uploadProgress!} fileCount={staged.length} />
							) : (
								<>
									<div
										className="pixel"
										style={{
											fontSize: 14,
											color: 'var(--lg-amber)',
											letterSpacing: '0.15em',
										}}
									>
										{extractStatus || 'EXTRACTION IN PROGRESS'}
									</div>
									{allTables.length > 0 ? (
										<>
											<div
												className="mono"
												style={{
													fontSize: 11,
													color: 'var(--lg-ink-dim)',
												}}
											>
												{doneTables.length} OF {allTables.length} TABLES EXTRACTED
											</div>
											{doneTables.length < allTables.length && (
												<div
													className="mono"
													style={{
														fontSize: 11,
														color: 'var(--lg-ink)',
													}}
												>
													→ {allTables[doneTables.length]}
												</div>
											)}
										</>
									) : (
										<>
											<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-mute)' }}>
												{staged.some((s) => isDbFile(s.file.name))
													? 'Connecting to database…'
													: 'Processing files server-side…'}
											</div>
											<div
												className="mono"
												style={{
													fontSize: 10,
													color: 'var(--lg-ink-mute)',
													maxWidth: 360,
													lineHeight: 1.5,
												}}
											>
												Reading and indexing your data into staging files. Large uploads take a
												moment.
											</div>
										</>
									)}
									<div
										className="mono"
										style={{
											fontSize: 10,
											color: 'var(--lg-ink-mute)',
											marginTop: 8,
											maxWidth: 360,
											lineHeight: 1.6,
										}}
									>
										Extraction continues server-side. You can leave this page and come back —
										progress is saved.
									</div>
								</>
							)}
						</div>
					) : (
						<div
							className={`rl-drop ${dragOver ? 'dragover' : ''}`}
							onDragOver={onDragOver}
							onDragEnter={onDragOver}
							onDragLeave={onDragLeave}
							onDrop={onDrop}
							onClick={() => inputRef.current?.click()}
							role="button"
							tabIndex={0}
						>
							<div className="sprite-disk" style={{ margin: '0 auto 14px' }} />
							<div className="pixel" style={{ fontSize: 12, color: 'var(--lg-amber)' }}>
								DROP FILES HERE
							</div>
							<div
								className="mono"
								style={{
									fontSize: 11,
									color: 'var(--lg-ink-mute)',
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
								style={{ display: 'none' }}
							/>
						</div>
					)}

					{!uploading && staged.length > 0 && (
						<div style={{ marginTop: 16 }}>
							<div
								className="pixel"
								style={{
									fontSize: 10,
									color: 'var(--lg-ink-dim)',
									letterSpacing: '0.1em',
									marginBottom: 8,
								}}
							>
								STAGED · {staged.length} FILE{staged.length === 1 ? '' : 'S'}
							</div>
							<div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
								{staged.map((s, i) => (
									<div key={s.file.name + i} className="rl-file-row">
										<IDisk size={12} />
										<div style={{ flex: 1, minWidth: 0 }}>
											<div style={{ fontSize: 12 }}>{s.file.name}</div>
											<div
												style={{
													fontSize: 10,
													color: 'var(--lg-ink-mute)',
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
									style={{ marginTop: 10, padding: '4px 10px', fontSize: 10 }}
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
								color: 'var(--lg-coral)',
								marginTop: 12,
							}}
						>
							{'> '}
							{error}
						</div>
					)}
				</div>
			</div>
			<div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
				{!uploading && (
					<div className="panel">
						<div className="panel-head">READY TO UPLOAD</div>
						<div className="panel-body">
							{staged.length === 0 ? (
								<div className="mono" style={{ fontSize: 11, color: 'var(--lg-ink-mute)' }}>
									Add files to begin.
								</div>
							) : (
								<>
									<div className="pixel" style={{ fontSize: 14, color: 'var(--lg-amber)' }}>
										{staged.length} FILE{staged.length === 1 ? '' : 'S'}
									</div>
									<div
										className="mono"
										style={{
											fontSize: 11,
											color: 'var(--lg-ink-dim)',
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
												color: 'var(--lg-coral)',
												marginTop: 8,
											}}
										>
											! MIXING DB AND FLAT FILES — ONLY THE DB FILE WILL BE EXTRACTED
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
						<div
							className="panel-body"
							style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
						>
							{addingNew ? (
								<div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
									<input
										type="text"
										value={newPassword}
										onChange={(e) => setNewPassword(e.target.value)}
										onKeyDown={(e) => {
											if (e.key === 'Enter') {
												e.preventDefault();
												handleAddNewPassword();
											} else if (e.key === 'Escape') {
												setAddingNew(false);
												setNewPassword('');
											}
										}}
										placeholder="New password"
										autoFocus
										style={{
											background: 'var(--lg-bg-panel, #111)',
											border: '1px solid var(--lg-ink-dim, #555)',
											color: 'var(--lg-ink, #ddd)',
											fontFamily: 'var(--lg-mono)',
											fontSize: 12,
											padding: '6px 8px',
										}}
									/>
									<div style={{ display: 'flex', gap: 6 }}>
										<button
											className="btn btn-primary"
											style={{ fontSize: 10, padding: '4px 10px', flex: 1 }}
											onClick={handleAddNewPassword}
										>
											SAVE
										</button>
										<button
											className="btn btn-ghost"
											style={{ fontSize: 10, padding: '4px 10px', flex: 1 }}
											onClick={() => {
												setAddingNew(false);
												setNewPassword('');
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
											if (e.target.value === '__add__') {
												setAddingNew(true);
											} else {
												setSelectedPassword(e.target.value);
											}
										}}
										style={{
											background: 'var(--lg-bg-panel, #111)',
											border: '1px solid var(--lg-ink-dim, #555)',
											color: 'var(--lg-ink, #ddd)',
											fontFamily: 'var(--lg-mono)',
											fontSize: 12,
											padding: '6px 8px',
											width: '100%',
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
									<div className="mono" style={{ fontSize: 10, color: 'var(--lg-ink-mute)' }}>
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
							{extractStatus || 'EXTRACTING'}
							{allTables.length > 0 && (
								<span
									style={{
										float: 'right',
										fontFamily: 'var(--lg-mono)',
										color: 'var(--lg-amber)',
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
										background: 'var(--lg-ink-dim, #333)',
										marginBottom: 10,
										position: 'relative',
										overflow: 'hidden',
									}}
								>
									<div
										style={{
											position: 'absolute',
											top: 0,
											left: 0,
											bottom: 0,
											background: 'var(--lg-amber, #f5b32a)',
											width: `${(doneTables.length / allTables.length) * 100}%`,
											transition: 'width 120ms linear',
										}}
									/>
								</div>
							)}
							<div
								ref={tableLogRef}
								style={{
									maxHeight: 220,
									overflowY: 'auto',
									fontFamily: 'var(--lg-mono)',
									fontSize: 11,
									display: 'flex',
									flexDirection: 'column',
									gap: 2,
								}}
							>
								{doneTables.map((t) => (
									<div key={t.name} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
										<ICheck size={8} />
										<span style={{ flex: 1, color: 'var(--lg-ink, #ddd)' }}>{t.name}</span>
										<span style={{ color: 'var(--lg-ink-mute, #999)' }}>
											{t.rows.toLocaleString()}
										</span>
									</div>
								))}
								{allTables.length > 0 && doneTables.length < allTables.length && (
									<div
										style={{
											display: 'flex',
											gap: 6,
											alignItems: 'center',
											color: 'var(--lg-ink-mute, #999)',
										}}
									>
										<span style={{ width: 8 }}>›</span>
										<span style={{ flex: 1 }}>{allTables[doneTables.length]}…</span>
									</div>
								)}
								{doneTables.length === 0 && allTables.length === 0 && (
									<div style={{ color: 'var(--lg-ink-mute, #999)' }}>{extractStatus}</div>
								)}
							</div>
						</div>
					</div>
				)}

				{uploading ? (
					<div style={{ display: 'flex', gap: 8 }}>
						<button className="btn btn-primary" disabled style={{ flex: 1 }}>
							UPLOADING… <IArrow size={10} />
						</button>
						<button
							className="btn btn-ghost"
							onClick={handleCancel}
							disabled={cancelling}
							style={{ minWidth: 110 }}
						>
							{cancelling ? 'CANCELLING…' : 'CANCEL'} <IX size={10} />
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
