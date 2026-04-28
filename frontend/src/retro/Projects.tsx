import { useEffect, useMemo, useState } from "react";
import { RL_STAGES, phaseEarnedXp, type Project } from "./data";
import { useAuth } from "./Auth";
import { IArrow, ICheck, IDisk, IDot, IDownload, IPlus, IStar, IX } from "./icons";
import { useKeyboardLayout } from "./keyboard";
import { RlPromptModal } from "./PromptModal";
import { RlTopbar } from "./Topbar";
import { XPBar } from "./XPBar";

const PHASE_TO_STAGE: Record<string, number> = {
	upload: 1,
	"pre-extract": 2,
	edit: 2,
	configure: 2,
	transform: 3,
	map: 3,
	load: 4,
	stats: 4,
};

type ProjectStatus = "draft" | "running" | "done" | "error";
type Filter = "all" | ProjectStatus;

function phaseStageIndex(phase: string): number {
	return PHASE_TO_STAGE[phase] ?? 0;
}

function phaseLabel(phase: string): string {
	const idx = phaseStageIndex(phase);
	return RL_STAGES[Math.max(0, idx - 1)]?.label ?? phase.toUpperCase();
}

function projectStatus(p: Project): ProjectStatus {
	if (p.phase === "stats" || p.phase === "load") return "done";
	if (!p.phase || p.phase === "upload") return "draft";
	return "running";
}

function timeAgo(iso: string): string {
	try {
		const diff = Date.now() - new Date(iso).getTime();
		const mins = Math.floor(diff / 60000);
		if (mins < 1) return "JUST NOW";
		if (mins < 60) return `${mins}M AGO`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}H AGO`;
		const days = Math.floor(hrs / 24);
		return `${days}D AGO`;
	} catch {
		return iso;
	}
}

export function RlProjects({
	onOpen,
	onNew,
}: {
	onOpen: (p: Project) => void;
	onNew: () => void;
}) {
	const { user } = useAuth();
	const [projects, setProjects] = useState<Project[]>([]);
	const [loading, setLoading] = useState(true);
	const [error, setError] = useState<string | null>(null);
	const [filter, setFilter] = useState<Filter>("all");
	const [dashStats, setDashStats] = useState<{
		total_rows_migrated: number;
		avg_quality_score: number;
	} | null>(null);
	const [renameTarget, setRenameTarget] = useState<string | null>(null);
	const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

	useEffect(() => {
		if (!user) {
			setProjects([]);
			setLoading(false);
			return;
		}
		setLoading(true);
		fetch(`/api/projects?username=${encodeURIComponent(user.username)}`)
			.then((r) => r.json())
			.then((data) => {
				setProjects(data.projects ?? []);
				setLoading(false);
			})
			.catch(() => {
				setError("FAILED TO LOAD PROJECTS");
				setLoading(false);
			});
		fetch(`/api/dashboard-stats?username=${encodeURIComponent(user.username)}`)
			.then((r) => r.json())
			.then((data) => setDashStats(data))
			.catch(() => {});
	}, [user]);

	const submitRename = async (newName: string) => {
		if (!renameTarget) return;
		const projectId = renameTarget;
		setRenameTarget(null);
		try {
			const res = await fetch(`/api/projects/${projectId}`, {
				method: "PATCH",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ name: newName }),
			});
			if (res.ok) {
				const updated = await res.json();
				setProjects((prev) =>
					prev.map((p) => (p.id === projectId ? { ...p, name: updated.name } : p)),
				);
			}
		} catch { /* ignore */ }
	};

	const confirmDelete = async (projectId: string) => {
		setDeleteTarget(null);
		try {
			const res = await fetch(`/api/projects/${projectId}`, { method: "DELETE" });
			if (res.ok) setProjects((prev) => prev.filter((p) => p.id !== projectId));
		} catch { /* ignore */ }
	};

	const filtered = filter === "all" ? projects : projects.filter((p) => projectStatus(p) === filter);

	// Build the keyboard layout for the page:
	//   row 0: [START_NEW_DUNGEON CTA]
	//   row 1: [filter_all, filter_running, filter_done, filter_draft]
	//   row 2..n: dungeon cards (3 per row)
	const FILTERS: Filter[] = ["all", "running", "done", "draft"];
	const layoutRows = useMemo(() => {
		const rows: { id: string; onActivate?: () => void }[][] = [];
		rows.push([{ id: "cta:new", onActivate: onNew }]);
		rows.push(FILTERS.map((f) => ({ id: `filter:${f}`, onActivate: () => setFilter(f) })));
		for (let i = 0; i < filtered.length; i += 3) {
			rows.push(
				filtered.slice(i, i + 3).map((p) => ({
					id: `card:${p.id}`,
					onActivate: () => onOpen(p),
				})),
			);
		}
		return rows;
	}, [filtered, onNew, onOpen]);
	const layout = useKeyboardLayout(layoutRows, {
		enabled: !renameTarget && !deleteTarget,
		// Land on the first dungeon card if there are any, else on the CTA.
		initial: filtered.length > 0 ? { row: 2, col: 0 } : { row: 0, col: 0 },
	});
	const running = projects.filter((p) => projectStatus(p) === "running").length;
	const done = projects.filter((p) => projectStatus(p) === "done").length;
	const drafts = projects.filter((p) => projectStatus(p) === "draft").length;
	const totalRows = dashStats?.total_rows_migrated ?? 0;
	const quality = dashStats?.avg_quality_score ?? 0;
	const totalXp = projects.reduce((acc, p) => acc + phaseEarnedXp(p.phase), 0);

	return (
		<div className="rl-page">
			<RlTopbar
				title="▼ DUNGEON HUB"
				sub="ONE LEGACY DATABASE PER DUNGEON · ONE PIPELINE EACH"
				center={<XPBar value={totalXp} />}
				right={
					<button className="btn btn-primary" onClick={onNew}>
						<IPlus size={10} /> NEW DUNGEON
					</button>
				}
			/>

			<div className="rl-stats">
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">RUNNING</div>
					<div className="rl-stat-value pixel glow-magenta" style={{ color: "var(--lg-magenta)" }}>
						{String(running).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">
						+{done} CLEARED · {drafts} DRAFT · {projects.length} TOTAL
					</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ROWS MIGRATED</div>
					<div className="rl-stat-value pixel glow-cyan" style={{ color: "var(--lg-cyan)" }}>
						{totalRows.toLocaleString()}
					</div>
					<div className="rl-stat-sub">
						<IStar size={8} /> ACROSS ALL PROJECTS
					</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">QUALITY</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: quality >= 80 ? "var(--lg-cyan)" : "var(--lg-coral)" }}
					>
						{dashStats ? quality : "—"}
					</div>
					<div className="rl-stat-sub">AVG SCORE</div>
				</div>
				{(() => {
					const k = layout.getItemProps("cta:new");
					return (
						<div
							className={`panel rl-stat rl-stat-cta ${k.className}`}
							onClick={onNew}
							onMouseEnter={k.onMouseEnter}
						>
							<div className="rl-stat-label pixel">NEW</div>
							<div
								style={{
									fontFamily: "var(--lg-pixel-tall)",
									fontSize: 28,
									lineHeight: 1.1,
									marginTop: 4,
								}}
							>
								START A NEW
								<br />
								DUNGEON
							</div>
							<div style={{ marginTop: 10 }}>
								<IPlus size={14} />
							</div>
						</div>
					);
				})()}
			</div>

			<div className="rl-section-head">
				<div className="pixel glow-cyan" style={{ fontSize: 10, color: "var(--lg-cyan)" }}>
					★ ACTIVE DUNGEONS ★
				</div>
				<div className="rl-filters">
					{FILTERS.map((f) => {
						const k = layout.getItemProps(`filter:${f}`);
						return (
							<button
								key={f}
								className={`btn ${filter === f ? "btn-primary" : "btn-ghost"} ${k.className}`}
								style={{ padding: "4px 10px", fontSize: 9 }}
								onClick={() => setFilter(f)}
								onMouseEnter={k.onMouseEnter}
							>
								{f.toUpperCase()}
							</button>
						);
					})}
				</div>
			</div>

			{loading ? (
				<div className="panel" style={{ padding: 40, textAlign: "center" }}>
					<div className="pixel blink" style={{ fontSize: 11, color: "var(--lg-magenta)" }}>
						LOADING…
					</div>
				</div>
			) : error ? (
				<div className="panel" style={{ padding: 40, textAlign: "center" }}>
					<div className="mono" style={{ fontSize: 11, color: "var(--lg-coral)" }}>{error}</div>
				</div>
			) : filtered.length === 0 ? (
				<div className="panel" style={{ padding: 40, textAlign: "center" }}>
					<div className="pixel" style={{ fontSize: 11, color: "var(--lg-ink-mute)" }}>
						{projects.length === 0 ? "NO DUNGEONS — START A NEW ONE" : "NO DUNGEONS MATCH FILTER"}
					</div>
				</div>
			) : (
				<div className="rl-proj-grid">
					{filtered.map((p) => (
						<RlProjectCard
							key={p.id}
							p={p}
							onOpen={onOpen}
							onRename={(e, id) => { e.stopPropagation(); setRenameTarget(id); }}
							onDelete={(e, id) => { e.stopPropagation(); setDeleteTarget(id); }}
							kbProps={layout.getItemProps(`card:${p.id}`)}
						/>
					))}
				</div>
			)}

			{renameTarget && (
				<RlPromptModal
					title="RENAME PROJECT"
					label="NEW PROJECT NAME"
					placeholder="new-name"
					confirmText="RENAME"
					onConfirm={submitRename}
					onCancel={() => setRenameTarget(null)}
				/>
			)}

			{deleteTarget && (
				<DeleteConfirmModal
					onCancel={() => setDeleteTarget(null)}
					onConfirm={() => confirmDelete(deleteTarget)}
				/>
			)}
		</div>
	);
}

function StatusBadge({ status }: { status: ProjectStatus }) {
	if (status === "running")
		return <span className="badge badge-cyan"><IDot size={6} c="var(--lg-cyan)" /> RUNNING</span>;
	if (status === "done")
		return <span className="badge badge-solid-lime"><ICheck size={8} /> CLEARED</span>;
	if (status === "error")
		return <span className="badge badge-err"><IX size={8} /> ERROR</span>;
	return <span className="badge badge-mute">DRAFT</span>;
}

function RlProjectCard({
	p,
	onOpen,
	onRename,
	onDelete,
	kbProps,
}: {
	p: Project;
	onOpen: (p: Project) => void;
	onRename: (e: React.MouseEvent, id: string) => void;
	onDelete: (e: React.MouseEvent, id: string) => void;
	kbProps?: { className: string; onMouseEnter?: () => void };
}) {
	const stageIdx = phaseStageIndex(p.phase);
	const progress = Math.round((stageIdx / 4) * 100);
	const status = projectStatus(p);
	const [showFiles, setShowFiles] = useState(false);
	const [outputFiles, setOutputFiles] = useState<string[]>([]);
	const isExported = p.phase === "load" || p.phase === "stats";

	const toggleFiles = async (e: React.MouseEvent) => {
		e.stopPropagation();
		if (showFiles) {
			setShowFiles(false);
			return;
		}
		try {
			const res = await fetch(`/api/projects/${p.id}/outputs`);
			if (res.ok) {
				const data = await res.json();
				setOutputFiles(data.files ?? []);
			}
		} catch { /* ignore */ }
		setShowFiles(true);
	};

	return (
		<div
			className={`rl-proj corners ${kbProps?.className ?? ""}`}
			onClick={() => onOpen(p)}
			onMouseEnter={kbProps?.onMouseEnter}
		>
			<div className="corner-tl" />
			<div className="corner-tr" />
			<div className="corner-bl" />
			<div className="corner-br" />

			<div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
				<div style={{ flex: 1, minWidth: 0 }}>
					<div className="pixel glow-magenta" style={{ fontSize: 11, lineHeight: 1.5, color: "var(--lg-magenta)", overflow: "hidden", textOverflow: "ellipsis" }}>
						{p.name.toUpperCase()}
					</div>
				</div>
				<StatusBadge status={status} />
			</div>

			<div className="rl-proj-path">
				<IDisk size={10} />
				<span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
					{phaseLabel(p.phase)}
				</span>
				<IArrow size={10} />
				<span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: "var(--lg-cyan)" }}>
					STEP {stageIdx}/4
				</span>
			</div>

			<div style={{ marginTop: 10 }}>
				<div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "var(--lg-cyan)", fontFamily: "var(--lg-pixel)", letterSpacing: "0.1em", marginBottom: 5 }}>
					<span>STAGE {stageIdx}/4 · {phaseLabel(p.phase)}</span>
					<span>{progress}%</span>
				</div>
				<div className="progress">
					<span style={{ width: progress + "%" }} />
				</div>
			</div>

			<div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", alignItems: "center", fontFamily: "var(--lg-pixel)", fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.1em" }}>
				<span>{p.username.toUpperCase()}</span>
				<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
					<span>{timeAgo(p.updated_at)}</span>
					{isExported && (
						<button
							className="link"
							style={{ fontSize: 9, color: showFiles ? "var(--lg-magenta)" : "var(--lg-cyan)" }}
							onClick={toggleFiles}
							title="Download exports"
						>
							<IDownload size={9} />
						</button>
					)}
					<button
						className="btn btn-ghost"
						style={{ fontSize: 10, padding: "4px 10px", color: "var(--lg-cyan)" }}
						onClick={(e) => onRename(e, p.id)}
						title="Rename project"
					>
						✎ RENAME
					</button>
					<button
						className="btn btn-ghost"
						style={{ fontSize: 10, padding: "4px 10px", color: "var(--lg-coral)" }}
						onClick={(e) => onDelete(e, p.id)}
						title="Delete project"
					>
						<IX size={9} /> DELETE
					</button>
				</div>
			</div>

			{showFiles && (
				<div onClick={(e) => e.stopPropagation()} style={{ marginTop: 10, borderTop: "1px solid var(--lg-border)", paddingTop: 10 }}>
					<div className="pixel" style={{ fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.1em", marginBottom: 6 }}>
						OUTPUT FILES
					</div>
					{outputFiles.length === 0 ? (
						<div className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
							No output files yet. Open project and run export.
						</div>
					) : (
						<div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
							{outputFiles.map((file) => (
								<div key={file} style={{ display: "flex", alignItems: "center", gap: 6 }}>
									<IDisk size={8} />
									<span className="mono" style={{ flex: 1, fontSize: 10, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
										{file}
									</span>
									<a
										href={`/api/projects/${p.id}/download/${file}`}
										download
										className="btn btn-ghost"
										style={{ padding: "2px 8px", fontSize: 8 }}
									>
										GET
									</a>
								</div>
							))}
						</div>
					)}
				</div>
			)}
		</div>
	);
}

function DeleteConfirmModal({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
	return (
		<div
			style={{
				position: "fixed", inset: 0, zIndex: 9999,
				background: "rgba(0,0,0,0.75)",
				display: "flex", alignItems: "center", justifyContent: "center", padding: 24,
			}}
			onClick={onCancel}
		>
			<div
				style={{ background: "var(--lg-bg)", border: "2px solid var(--lg-coral)", width: 400, maxWidth: "90vw" }}
				onClick={(e) => e.stopPropagation()}
			>
				<div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px solid var(--lg-border)", background: "var(--lg-bg-2)" }}>
					<span className="pixel" style={{ fontSize: 11, color: "var(--lg-coral)", letterSpacing: "0.1em" }}>
						DELETE PROJECT
					</span>
				</div>
				<div style={{ padding: "20px 14px" }}>
					<div className="pixel" style={{ fontSize: 10, color: "var(--lg-ink)", marginBottom: 12, lineHeight: 1.6 }}>
						Delete this project? This cannot be undone.
					</div>
				</div>
				<div style={{ display: "flex", justifyContent: "flex-end", gap: 8, padding: "0 14px 14px" }}>
					<button className="btn btn-ghost" style={{ padding: "6px 14px", fontSize: 10 }} onClick={onCancel}>
						CANCEL
					</button>
					<button className="btn btn-coral" style={{ padding: "6px 14px", fontSize: 10 }} onClick={onConfirm}>
						DELETE
					</button>
				</div>
			</div>
		</div>
	);
}
