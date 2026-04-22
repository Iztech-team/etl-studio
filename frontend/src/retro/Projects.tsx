import { RL_PROJECTS, RL_STAGES, type Project } from "./data";
import { IArrow, ICheck, IDisk, IDot, IPlus, IX } from "./icons";
import { SpriteMonitor, Sparkles } from "./Sprites";
import { RlTopbar } from "./Topbar";

export function RlProjects({
	onOpen,
	onNew,
}: {
	onOpen: (p: Project) => void;
	onNew: () => void;
}) {
	const running = RL_PROJECTS.filter((p) => p.status === "running").length;
	const done = RL_PROJECTS.filter((p) => p.status === "done").length;
	const errors = RL_PROJECTS.filter((p) => p.status === "error").length;
	const isEmpty = RL_PROJECTS.length === 0;

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
					<div className="rl-stat-label pixel">RUNNING</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: "var(--lg-amber)" }}
					>
						{String(running).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">
						{done} DONE · {RL_PROJECTS.length} TOTAL
					</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ROWS MIGRATED</div>
					<div className="rl-stat-value pixel" style={{ color: "var(--lg-ink)" }}>
						0
					</div>
					<div className="rl-stat-sub">ACROSS ALL PROJECTS</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ERRORS</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: errors ? "var(--lg-coral)" : "var(--lg-ink-mute)" }}
					>
						{String(errors).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">
						{errors ? "NEEDS ATTENTION" : "ALL CLEAR"}
					</div>
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
						UPLOAD .IB
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
				<div className="rl-filters">
					<select className="select" style={{ width: 160 }} disabled={isEmpty}>
						<option>ALL STATUSES</option>
						<option>RUNNING</option>
						<option>DONE</option>
						<option>ERROR</option>
						<option>DRAFT</option>
					</select>
					<select className="select" style={{ width: 140 }} disabled={isEmpty}>
						<option>RECENT</option>
						<option>NAME A–Z</option>
						<option>SIZE</option>
					</select>
				</div>
			</div>

			{isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot">
							<SpriteMonitor size={96} />
						</div>
						<div className="rl-empty-title">NO PROJECTS YET</div>
						<div className="rl-empty-sub">
							Your legacy data awakens when you upload an .IB file. Each project
							runs one pipeline from extract to export.
						</div>
						<button className="btn btn-primary" onClick={onNew}>
							<IPlus size={10} /> CREATE FIRST PROJECT
						</button>
					</div>
				</div>
			) : (
				<div className="rl-proj-grid">
					{RL_PROJECTS.map((p) => (
						<RlProjectCard key={p.id} p={p} onOpen={onOpen} />
					))}
				</div>
			)}
		</div>
	);
}

function RlProjectCard({
	p,
	onOpen,
}: {
	p: Project;
	onOpen: (p: Project) => void;
}) {
	const status = {
		running: (
			<span className="badge badge-ok">
				<IDot size={6} /> RUNNING
			</span>
		),
		done: (
			<span className="badge badge-solid">
				<ICheck size={8} /> DONE
			</span>
		),
		error: (
			<span className="badge badge-err">
				<IX size={8} /> ERROR
			</span>
		),
		draft: <span className="badge badge-mute">DRAFT</span>,
	}[p.status];

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
						{p.name}
					</div>
					<div
						className="mono"
						style={{
							fontSize: 11,
							color: "var(--lg-ink-mute)",
							marginTop: 4,
						}}
					>
						{p.desc}
					</div>
				</div>
				{status}
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
					{p.source}
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
					{p.target}
				</span>
			</div>

			{p.error && (
				<div
					style={{
						fontSize: 10,
						color: "var(--lg-coral)",
						fontFamily: "var(--lg-mono)",
						marginTop: 10,
						display: "flex",
						gap: 6,
					}}
				>
					<span>!</span>
					<span>{p.error}</span>
				</div>
			)}

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
						STEP {p.stage}/6 ·{" "}
						{RL_STAGES[Math.max(0, p.stage - 1)]?.label || "—"}
					</span>
					<span>{p.progress}%</span>
				</div>
				<div className="progress">
					<span style={{ width: p.progress + "%" }} />
				</div>
			</div>

			<div
				style={{
					marginTop: 10,
					display: "flex",
					justifyContent: "space-between",
					fontFamily: "var(--lg-pixel)",
					fontSize: 8,
					color: "var(--lg-ink-mute)",
					letterSpacing: "0.1em",
				}}
			>
				<span>{p.owner}</span>
				<span>{p.updated}</span>
			</div>
		</div>
	);
}
