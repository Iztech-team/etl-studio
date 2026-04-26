import { useEffect, useState } from "react";
import { RL_STAGES, type Project } from "./data";
import { useAuth } from "./Auth";
import { IArrow, IDisk, IDownload, IPlus, IX } from "./icons";
import { SpriteMonitor, Sparkles } from "./Sprites";
import { RlPromptModal } from "./PromptModal";
import { RlTopbar } from "./Topbar";

const PHASE_TO_STAGE: Record<string, number> = {
	upload: 1,
	"pre-extract": 2,
	edit: 2,
	configure: 2,
	transform: 3,
	map: 3, // legacy — same stage as transform now
	load: 4,
	stats: 4,
};

function phaseStageIndex(phase: string): number {
	return PHASE_TO_STAGE[phase] ?? 0;
}

function phaseLabel(phase: string): string {
	const idx = phaseStageIndex(phase);
	return RL_STAGES[Math.max(0, idx - 1)]?.label ?? phase.toUpperCase();
}

function timeAgo(iso: string): string {
	try {
		const d = new Date(iso);
		const diff = Date.now() - d.getTime();
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
	const [dashStats, setDashStats] = useState<{
		total_rows_migrated: number;
		avg_quality_score: number;
	} | null>(null);

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

	const [renameTarget, setRenameTarget] = useState<string | null>(null);

	const handleRename = (e: React.MouseEvent, projectId: string) => {
		e.stopPropagation();
		setRenameTarget(projectId);
	};

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
		} catch {
			// ignore
		}
	};

	const handleDelete = async (e: React.MouseEvent, projectId: string) => {
		e.stopPropagation();
		if (!confirm("Delete this project? This cannot be undone.")) return;
		try {
			const res = await fetch(`/api/projects/${projectId}`, {
				method: "DELETE",
			});
			if (res.ok) {
				setProjects((prev) => prev.filter((p) => p.id !== projectId));
			}
		} catch {
			// ignore
		}
	};

	const isEmpty = projects.length === 0;
	const doneCount = projects.filter((p) => p.phase === "stats").length;

	return (
		<div className="rl-page">
			<RlTopbar
				title="PROJECTS"
				sub="ONE LEGACY DATABASE PER PROJECT · ONE PIPELINE EACH"
				right={
					<button className="btn btn-primary" onClick={onNew}>
						<IPlus size={10} /> NEW PROJECT
					</button>
				}
			/>

			<div className="rl-stats">
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">PROJECTS</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: "var(--lg-amber)" }}
					>
						{String(projects.length).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">
						{doneCount} DONE · {projects.length} TOTAL
					</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ROWS MIGRATED</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: "var(--lg-ink)" }}
					>
						{(dashStats?.total_rows_migrated ?? 0).toLocaleString()}
					</div>
					<div className="rl-stat-sub">ACROSS ALL PROJECTS</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">QUALITY</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: (dashStats?.avg_quality_score ?? 0) >= 80 ? "var(--lg-ink)" : "var(--lg-coral)" }}
					>
						{dashStats?.avg_quality_score ?? "—"}
					</div>
					<div className="rl-stat-sub">AVG SCORE</div>
				</div>
				<div className="panel rl-stat rl-stat-cta" onClick={onNew}>
					<div className="rl-stat-label pixel">NEW</div>
					<div
						style={{
							fontFamily: "var(--lg-pixel-tall)",
							fontSize: 28,
							color: "var(--lg-bg)",
							lineHeight: 1.1,
							marginTop: 4,
						}}
					>
						UPLOAD FILE
						<br />
						TO CREATE
					</div>
					<div style={{ marginTop: 10 }}>
						<IPlus size={14} />
					</div>
				</div>
			</div>

			<div className="rl-section-head">
				<div
					className="pixel"
					style={{
						fontSize: 10,
						color: "var(--lg-ink-dim)",
						letterSpacing: "0.1em",
					}}
				>
					* YOUR PROJECTS *
				</div>
			</div>

			{loading ? (
				<div
					className="panel"
					style={{ padding: 40, textAlign: "center" }}
				>
					<div
						className="pixel"
						style={{
							fontSize: 11,
							color: "var(--lg-amber)",
							letterSpacing: "0.1em",
						}}
					>
						LOADING…
					</div>
				</div>
			) : error ? (
				<div
					className="panel"
					style={{ padding: 40, textAlign: "center" }}
				>
					<div
						className="mono"
						style={{ fontSize: 11, color: "var(--lg-coral)" }}
					>
						{error}
					</div>
				</div>
			) : isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot">
							<SpriteMonitor size={96} />
						</div>
						<div className="rl-empty-title">NO PROJECTS YET</div>
						<div className="rl-empty-sub">
							Your legacy data awakens when you upload a database file. Each
							project runs one pipeline from extract to export.
						</div>
						<button className="btn btn-primary" onClick={onNew}>
							<IPlus size={10} /> CREATE FIRST PROJECT
						</button>
					</div>
				</div>
			) : (
				<div className="rl-proj-grid">
					{projects.map((p) => (
						<RlProjectCard
							key={p.id}
							p={p}
							onOpen={onOpen}
							onDelete={handleDelete}
							onRename={handleRename}
						/>
					))}
				</div>
			)}

			<div style={{ marginTop: 40, marginBottom: 20 }}>
				<div className="rl-section-head">
					<div
						className="pixel"
						style={{
							fontSize: 10,
							color: "var(--lg-ink-dim)",
							letterSpacing: "0.1em",
						}}
					>
						* KEYBOARD SHORTCUTS *
					</div>
				</div>
				<div className="panel" style={{ padding: 14 }}>
					<div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 20 }}>
						<div>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-amber)",
									letterSpacing: "0.08em",
									marginBottom: 8,
								}}
							>
								EXTRACT PHASE
							</div>
							<div style={{ fontSize: 10, fontFamily: "var(--lg-mono)", lineHeight: 1.6, color: "var(--lg-ink-dim)" }}>
								<div><strong>↑ / ↓</strong> · Navigate tables</div>
								<div><strong>D / Space</strong> · Toggle keep/drop</div>
								<div><strong>P</strong> · Preview table</div>
								<div><strong>E</strong> · Deselect empty</div>
								<div><strong>A</strong> · Toggle all</div>
							</div>
						</div>
						<div>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-amber)",
									letterSpacing: "0.08em",
									marginBottom: 8,
								}}
							>
								TRANSFORM PHASE — COLUMNS
							</div>
							<div style={{ fontSize: 10, fontFamily: "var(--lg-mono)", lineHeight: 1.6, color: "var(--lg-ink-dim)" }}>
								<div><strong>↑ / ↓</strong> · Navigate columns</div>
								<div><strong>D</strong> · Toggle DROP</div>
								<div><strong>C</strong> · Toggle CAST</div>
							</div>
						</div>
						<div>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: "var(--lg-amber)",
									letterSpacing: "0.08em",
									marginBottom: 8,
								}}
							>
								TRANSFORM PHASE — TABLES
							</div>
							<div style={{ fontSize: 10, fontFamily: "var(--lg-mono)", lineHeight: 1.6, color: "var(--lg-ink-dim)" }}>
								<div><strong>Tab / Shift+Tab</strong> · Switch tables</div>
								<div><strong>Alt + R</strong> · Rename table</div>
							</div>
						</div>
					</div>
				</div>
			</div>

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
		</div>
	);
}

function RlProjectCard({
	p,
	onOpen,
	onDelete,
	onRename,
}: {
	p: Project;
	onOpen: (p: Project) => void;
	onDelete: (e: React.MouseEvent, id: string) => void;
	onRename: (e: React.MouseEvent, id: string) => void;
}) {
	const stageIdx = phaseStageIndex(p.phase);
	const progress = Math.round((stageIdx / 4) * 100);
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
		<div className="rl-proj corners" onClick={() => onOpen(p)}>
			<div className="corner-tl" />
			<div className="corner-tr" />
			<div className="corner-bl" />
			<div className="corner-br" />
			<div
				style={{
					display: "flex",
					alignItems: "flex-start",
					justifyContent: "space-between",
					gap: 10,
				}}
			>
				<div style={{ flex: 1 }}>
					<div
						className="pixel"
						style={{
							fontSize: 11,
							lineHeight: 1.5,
							color: "var(--lg-ink)",
						}}
					>
						{p.name.toUpperCase()}
					</div>
				</div>
				<span className="badge badge-mute">{phaseLabel(p.phase)}</span>
			</div>

			<div className="rl-proj-path">
				<IDisk size={10} />
				<span
					style={{
						flex: 1,
						overflow: "hidden",
						textOverflow: "ellipsis",
						whiteSpace: "nowrap",
					}}
				>
					{p.phase.toUpperCase()}
				</span>
				<IArrow size={10} />
				<span
					style={{
						flex: 1,
						overflow: "hidden",
						textOverflow: "ellipsis",
						whiteSpace: "nowrap",
					}}
				>
					STEP {stageIdx}/4
				</span>
			</div>

			<div style={{ marginTop: 12 }}>
				<div
					style={{
						display: "flex",
						justifyContent: "space-between",
						fontSize: 9,
						color: "var(--lg-ink-mute)",
						fontFamily: "var(--lg-pixel)",
						letterSpacing: "0.1em",
						marginBottom: 5,
					}}
				>
					<span>
						STEP {stageIdx}/4 · {phaseLabel(p.phase)}
					</span>
					<span>{progress}%</span>
				</div>
				<div className="progress">
					<span style={{ width: progress + "%" }} />
				</div>
			</div>

			<div
				style={{
					marginTop: 10,
					display: "flex",
					justifyContent: "space-between",
					alignItems: "center",
					fontFamily: "var(--lg-pixel)",
					fontSize: 8,
					color: "var(--lg-ink-mute)",
					letterSpacing: "0.1em",
				}}
			>
				<span>{p.username.toUpperCase()}</span>
				<div style={{ display: "flex", alignItems: "center", gap: 8 }}>
					<span>{timeAgo(p.updated_at)}</span>
					{isExported && (
						<button
							className="link"
							style={{ fontSize: 9, color: showFiles ? "var(--lg-amber)" : "var(--lg-ink)" }}
							onClick={toggleFiles}
							title="Download exports"
						>
							<IDownload size={9} />
						</button>
					)}
					<button
						className="link"
						style={{ fontSize: 9, color: "var(--lg-amber)" }}
						onClick={(e) => onRename(e, p.id)}
						title="Rename project"
					>
						✎
					</button>
					<button
						className="link"
						style={{ fontSize: 9, color: "var(--lg-coral)" }}
						onClick={(e) => onDelete(e, p.id)}
						title="Delete project"
					>
						<IX size={8} />
					</button>
				</div>
			</div>

			{showFiles && (
				<div
					onClick={(e) => e.stopPropagation()}
					style={{
						marginTop: 10,
						borderTop: "1px solid var(--lg-border)",
						paddingTop: 10,
					}}
				>
					<div
						className="pixel"
						style={{ fontSize: 8, color: "var(--lg-ink-mute)", letterSpacing: "0.1em", marginBottom: 6 }}
					>
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
