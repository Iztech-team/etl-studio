import { useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "./Auth";
import { RL_STAGES, type StageId } from "./data";
import { ICheck, IClock, IDisk, IFolder } from "./icons";

export function RlTopbar({
	title,
	sub,
	right,
}: {
	title: string;
	sub?: string;
	right?: ReactNode;
}) {
	return (
		<div className="rl-topbar">
			<div className="rl-topbar-title">
				<div
					className="pixel"
					style={{ fontSize: 18, color: "var(--lg-amber)" }}
				>
					{title}
				</div>
				{sub && (
					<div
						className="mono"
						style={{
							fontSize: 11,
							color: "var(--lg-ink-mute)",
							marginTop: 6,
							textTransform: "uppercase",
							letterSpacing: "0.1em",
						}}
					>
						{sub}
					</div>
				)}
			</div>
			<div style={{ flex: 1 }} />
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

type PageId = "projects" | "templates" | "history";

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
		{ id: "projects", label: "PROJECTS", I: IFolder },
		{ id: "templates", label: "TEMPLATES", I: IDisk },
		{ id: "history", label: "HISTORY", I: IClock },
	];
	const inPipe = pipelineStage != null;
	const activeIdx = RL_STAGES.findIndex((s) => s.id === pipelineStage);

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
			{inPipe ? (
				<div className="rl-dock-pipe">
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
				</div>
			) : (
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
			)}
		</div>
	);
}
