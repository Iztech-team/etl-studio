import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "./Auth";
import { RL_STAGES, type StageId } from "./data";
import { ICheck, IDisk, IFolder } from "./icons";

// Same key prefix Pipeline.tsx writes under. Kept in sync by convention —
// both must use the literal string. If you rename it, rename both places.
const ACTIVE_EXTRACTION_LS_PREFIX = "etl_studio.active_extraction.";
const ACTIVE_TRANSFORM_LS_PREFIX = "etl_studio.active_transform.";

type ActiveExtractionInfo = {
	sessionId: string;
	filename: string;
	done: number;
	total: number;
	current: string | null;
};

type ActiveTransformInfo = {
	sessionId: string;
	done: number;
	total: number;
	current: string | null;
};

// Poll-based hook so the dock can keep showing extraction progress even
// when the Pipeline component is unmounted (user navigated to projects /
// templates / history). The Pipeline owns the SSE consumer for its own
// progress UI; this is a lightweight independent observer.
function useActiveExtraction(): ActiveExtractionInfo | null {
	const [info, setInfo] = useState<ActiveExtractionInfo | null>(null);

	useEffect(() => {
		let cancelled = false;
		let timer: ReturnType<typeof setTimeout> | null = null;

		const scanLs = (): { sessionId: string; filename: string } | null => {
			for (let i = 0; i < localStorage.length; i++) {
				const key = localStorage.key(i);
				if (!key || !key.startsWith(ACTIVE_EXTRACTION_LS_PREFIX)) continue;
				try {
					const raw = localStorage.getItem(key);
					if (!raw) continue;
					const v = JSON.parse(raw) as {
						sessionId?: string;
						filename?: string;
					};
					if (v.sessionId)
						return {
							sessionId: v.sessionId,
							filename: v.filename ?? "",
						};
				} catch {
					// ignore corrupt entry
				}
			}
			return null;
		};

		const poll = async () => {
			if (cancelled) return;
			const active = scanLs();
			if (!active) {
				setInfo(null);
				timer = setTimeout(poll, 2500);
				return;
			}
			try {
				const res = await fetch(`/api/extract/${active.sessionId}/status`);
				if (res.ok) {
					const data = (await res.json()) as {
						status: string;
						tables_done?: number;
						tables_total?: number;
						current_table?: string | null;
					};
					if (cancelled) return;
					if (data.status === "extracting") {
						setInfo({
							sessionId: active.sessionId,
							filename: active.filename,
							done: data.tables_done ?? 0,
							total: data.tables_total ?? 0,
							current: data.current_table ?? null,
						});
						if (!cancelled) timer = setTimeout(poll, 1200);
						return;
					}
					// done / error / pending — stop showing
					setInfo(null);
				}
			} catch {
				// network blip, retry
			}
			if (!cancelled) timer = setTimeout(poll, 2500);
		};

		void poll();
		return () => {
			cancelled = true;
			if (timer) clearTimeout(timer);
		};
	}, []);

	return info;
}

// useActiveTransform was a poller for /api/transform/{sid}/status. The
// passthrough transform completes instantly so there's no progress to
// show; the hook now returns null until a real progress endpoint exists.
function useActiveTransform(): ActiveTransformInfo | null {
	return null;
}

export function RlTopbar({
	title,
	sub,
	center,
	right,
}: {
	title: string;
	sub?: string;
	center?: ReactNode;
	right?: ReactNode;
}) {
	return (
		<div className="rl-topbar">
			<div className="rl-topbar-title">
				<div
					className="pixel glow-magenta"
					style={{ fontSize: 18, color: "var(--lg-magenta)" }}
				>
					{title}
				</div>
				{sub && (
					<div
						className="mono"
						style={{
							fontSize: 11,
							color: "var(--lg-cyan)",
							marginTop: 6,
							textTransform: "uppercase",
							letterSpacing: "0.1em",
						}}
					>
						{sub}
					</div>
				)}
			</div>
			<div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
				{center}
			</div>
			{right}
			<UserButton />
		</div>
	);
}

function UserButton() {
	const { user, logout } = useAuth();
	const [open, setOpen] = useState(false);
	const ref = useRef<HTMLDivElement | null>(null);

	useEffect(() => {
		if (!open) return;
		const onDocDown = (e: MouseEvent) => {
			if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
		};
		const onKey = (e: KeyboardEvent) => {
			if (e.key === "Escape") setOpen(false);
		};
		document.addEventListener("mousedown", onDocDown);
		document.addEventListener("keydown", onKey);
		return () => {
			document.removeEventListener("mousedown", onDocDown);
			document.removeEventListener("keydown", onKey);
		};
	}, [open]);

	if (!user) return null;

	return (
		<div className="rl-user-wrap" ref={ref}>
			<button
				className={`rl-user rl-user-btn ${open ? "open" : ""}`}
				onClick={() => setOpen((v) => !v)}
				aria-haspopup="menu"
				aria-expanded={open}
			>
				<div className="rl-avatar">{user.initials}</div>
				<div>
					<div style={{ fontSize: 11 }}>{user.displayName}</div>
					<div
						style={{
							fontSize: 9,
							color: "var(--lg-ink-mute)",
							textTransform: "uppercase",
							letterSpacing: "0.1em",
						}}
					>
						{user.role}
					</div>
				</div>
			</button>
			{open && (
				<div className="rl-user-menu" role="menu">
					<div className="rl-user-menu-head">
						<div
							className="pixel"
							style={{
								fontSize: 9,
								color: "var(--lg-amber)",
								letterSpacing: "0.15em",
							}}
						>
							SIGNED IN
						</div>
						<div
							className="mono"
							style={{
								fontSize: 11,
								color: "var(--lg-ink)",
								marginTop: 4,
							}}
						>
							{user.displayName}
						</div>
						<div
							className="mono"
							style={{
								fontSize: 10,
								color: "var(--lg-ink-mute)",
								marginTop: 2,
							}}
						>
							@{user.username}
						</div>
					</div>
					<div className="rl-user-menu-sep" />
					<button
						className="rl-user-menu-item danger"
						onClick={() => {
							setOpen(false);
							logout();
						}}
					>
						▸ LOGOUT
					</button>
				</div>
			)}
		</div>
	);
}

type PageId = "projects";

function ExtractionDockView({ info }: { info: ActiveExtractionInfo }) {
	const pct = info.total > 0 ? Math.round((info.done / info.total) * 100) : 0;
	return (
		<>
			<div
				className="rl-dock-pipe-label pixel"
				style={{ color: "var(--lg-amber)" }}
			>
				EXTRACTING
			</div>
			<div
				style={{
					flex: 1,
					display: "flex",
					alignItems: "center",
					gap: 16,
					minWidth: 0,
				}}
			>
				<div
					className="mono"
					style={{
						fontSize: 11,
						color: "var(--lg-ink)",
						whiteSpace: "nowrap",
						overflow: "hidden",
						textOverflow: "ellipsis",
						maxWidth: 180,
					}}
					title={info.filename}
				>
					{info.filename || "database"}
				</div>
				<div
					style={{
						flex: 1,
						minWidth: 80,
						display: "flex",
						flexDirection: "column",
						gap: 4,
					}}
				>
					<div
						className="mono"
						style={{
							fontSize: 10,
							color: "var(--lg-ink-mute)",
							display: "flex",
							justifyContent: "space-between",
							gap: 8,
						}}
					>
						<span
							style={{
								flex: 1,
								overflow: "hidden",
								textOverflow: "ellipsis",
								whiteSpace: "nowrap",
							}}
						>
							{info.current ? `→ ${info.current}` : "starting…"}
						</span>
						<span style={{ color: "var(--lg-amber)", fontVariantNumeric: "tabular-nums" }}>
							{info.done}/{info.total || "?"} · {pct}%
						</span>
					</div>
					<div
						style={{
							height: 4,
							background: "var(--lg-bg-1, #222)",
							position: "relative",
							overflow: "hidden",
							border: "1px solid var(--lg-border, #333)",
						}}
					>
						<div
							style={{
								position: "absolute",
								top: 0,
								bottom: 0,
								left: 0,
								width: `${pct}%`,
								background: "var(--lg-amber, #f5b32a)",
								transition: "width 200ms linear",
							}}
						/>
					</div>
				</div>
			</div>
		</>
	);
}

function TransformDockView({ info }: { info: ActiveTransformInfo }) {
	const pct = info.total > 0 ? Math.round((info.done / info.total) * 100) : 0;
	return (
		<>
			<div
				className="rl-dock-pipe-label pixel"
				style={{ color: "var(--lg-amber)" }}
			>
				TRANSFORMING
			</div>
			<div
				style={{
					flex: 1,
					display: "flex",
					alignItems: "center",
					gap: 16,
					minWidth: 0,
				}}
			>
				<div
					style={{
						flex: 1,
						minWidth: 80,
						display: "flex",
						flexDirection: "column",
						gap: 4,
					}}
				>
					<div
						className="mono"
						style={{
							fontSize: 10,
							color: "var(--lg-ink-mute)",
							display: "flex",
							justifyContent: "space-between",
							gap: 8,
						}}
					>
						<span
							style={{
								flex: 1,
								overflow: "hidden",
								textOverflow: "ellipsis",
								whiteSpace: "nowrap",
							}}
						>
							{info.current ? `→ ${info.current}` : "starting…"}
						</span>
						<span style={{ color: "var(--lg-amber)", fontVariantNumeric: "tabular-nums" }}>
							{info.done}/{info.total || "?"} · {pct}%
						</span>
					</div>
					<div
						style={{
							height: 4,
							background: "var(--lg-bg-1, #222)",
							position: "relative",
							overflow: "hidden",
							border: "1px solid var(--lg-border, #333)",
						}}
					>
						<div
							style={{
								position: "absolute",
								top: 0,
								bottom: 0,
								left: 0,
								width: `${pct}%`,
								background: "var(--lg-amber, #f5b32a)",
								transition: "width 200ms linear",
							}}
						/>
					</div>
				</div>
			</div>
		</>
	);
}

function PipelineDockView({ activeIdx }: { activeIdx: number }) {
	return (
		<>
			<div className="rl-dock-pipe-label pixel">PIPELINE</div>
			<div className="rl-dock-pipe-track">
				{RL_STAGES.map((s, i) => {
					const done = i < activeIdx;
					const active = i === activeIdx;
					return (
						<div key={s.id} style={{ display: "contents" }}>
							<div
								className={`rl-dock-pipe-step ${done ? "done" : ""} ${active ? "active" : ""}`}
							>
								<div className="dot pixel">
									{done ? <ICheck size={8} /> : i + 1}
								</div>
								<div className="lab">{s.label}</div>
							</div>
							{i < RL_STAGES.length - 1 && (
								<div className={`rl-dock-pipe-sep ${done ? "done" : ""}`} />
							)}
						</div>
					);
				})}
			</div>
		</>
	);
}

export function RlDock({
	activePage,
	pipelineStage,
	onPage,
}: {
	activePage: PageId;
	pipelineStage: StageId | null;
	onPage: (id: PageId) => void;
}) {
	const pages: {
		id: PageId;
		label: string;
		I: (p: { size?: number }) => JSX.Element;
	}[] = [
		{ id: "projects", label: "DUNGEONS", I: IFolder },
	];
	const inPipe = pipelineStage != null;
	const activeIdx = RL_STAGES.findIndex((s) => s.id === pipelineStage);
	const extraction = useActiveExtraction();
	const transform = useActiveTransform();

	// Cross-fade rules:
	//  - If a transform is in progress, prefer it over the pipeline track —
	//    it's the most actionable status the user wants to see right now.
	//  - Extraction takes longer (often minutes) so when both extraction and
	//    pipeline context exist, alternate between them every few seconds.
	//  - If only the pipeline is active, show that.
	const overlay: "transform" | "extraction" | null = transform
		? "transform"
		: extraction
			? "extraction"
			: null;
	const [showOverlay, setShowOverlay] = useState(false);
	useEffect(() => {
		if (!overlay) {
			setShowOverlay(false);
			return;
		}
		if (!inPipe || overlay === "transform") {
			// Outside the pipeline, or transforming: lock the overlay on so
			// the progress bar is always visible while it runs.
			setShowOverlay(true);
			return;
		}
		setShowOverlay(true);
		const id = setInterval(() => setShowOverlay((v) => !v), 3500);
		return () => clearInterval(id);
	}, [overlay, inPipe]);

	const renderPipeArea = () => {
		if (!inPipe && !overlay) {
			return (
				<div className="rl-dock-pipe idle">
					<span
						className="pixel"
						style={{
							fontSize: 8,
							color: "var(--lg-ink-faint)",
							letterSpacing: "0.15em",
						}}
					>
						[ OPEN A PROJECT · PIPELINE PROGRESS SHOWS HERE ]
					</span>
				</div>
			);
		}
		// Render two stacked panels and cross-fade between them.
		const showingOverlay = !!overlay && showOverlay;
		return (
			<div className="rl-dock-pipe" style={{ position: "relative" }}>
				<div
					style={{
						display: "flex",
						alignItems: "center",
						width: "100%",
						transition: "opacity 350ms ease, transform 350ms ease",
						opacity: showingOverlay ? 0 : 1,
						transform: showingOverlay ? "translateY(-4px)" : "translateY(0)",
						pointerEvents: showingOverlay ? "none" : "auto",
						position: showingOverlay ? "absolute" : "relative",
						left: 0,
						right: 0,
						paddingLeft: 12,
						paddingRight: 12,
					}}
				>
					{inPipe ? (
						<PipelineDockView activeIdx={activeIdx} />
					) : (
						<span
							className="pixel"
							style={{
								fontSize: 8,
								color: "var(--lg-ink-faint)",
								letterSpacing: "0.15em",
								margin: "0 auto",
							}}
						>
							[ {overlay === "transform" ? "TRANSFORM" : "EXTRACTION"} IN PROGRESS ]
						</span>
					)}
				</div>
				<div
					style={{
						display: "flex",
						alignItems: "center",
						width: "100%",
						transition: "opacity 350ms ease, transform 350ms ease",
						opacity: showingOverlay ? 1 : 0,
						transform: showingOverlay ? "translateY(0)" : "translateY(4px)",
						pointerEvents: showingOverlay ? "auto" : "none",
						position: showingOverlay ? "relative" : "absolute",
						left: 0,
						right: 0,
						paddingLeft: 12,
						paddingRight: 12,
					}}
				>
					{transform ? (
						<TransformDockView info={transform} />
					) : extraction ? (
						<ExtractionDockView info={extraction} />
					) : null}
				</div>
			</div>
		);
	};

	return (
		<div className="rl-dock">
			<div className="rl-dock-brand pixel">LEGACY</div>
			<div className="rl-dock-pages">
				{pages.map((p) => {
					const active = p.id === activePage;
					const I = p.I;
					return (
						<div
							key={p.id}
							className={`rl-dock-page ${active ? "active" : ""}`}
							onClick={() => onPage(p.id)}
						>
							<I size={12} />
							<span>{p.label}</span>
						</div>
					);
				})}
			</div>
			<div className="rl-dock-divider" />
			{renderPipeArea()}
		</div>
	);
}
