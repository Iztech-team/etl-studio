import { useState } from "react";
import { RL_HISTORY, type HistoryStatus } from "./data";
import { IDot } from "./icons";
import { SpriteGhost, Sparkles } from "./Sprites";
import { RlTopbar } from "./Topbar";

type Filter = "all" | HistoryStatus;

export function RlHistory() {
	const [filter, setFilter] = useState<Filter>("all");
	const rows = RL_HISTORY.filter((r) => filter === "all" || r.status === filter);
	const totalRows = RL_HISTORY.reduce((a, r) => a + r.rows, 0);
	const done = RL_HISTORY.filter((r) => r.status === "done").length;
	const errors = RL_HISTORY.filter((r) => r.status === "error").length;
	const successRate = RL_HISTORY.length
		? Math.round((done / RL_HISTORY.length) * 100)
		: 0;
	const isEmpty = RL_HISTORY.length === 0;

	return (
		<div className="rl-page">
			<RlTopbar
				title="HISTORY"
				sub="EVERY PIPELINE RUN · NEWEST FIRST"
				right={
					<button className="btn btn-ghost" disabled={isEmpty}>
						EXPORT LOG
					</button>
				}
			/>

			<div className="rl-stats">
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">RUNS (7D)</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: "var(--lg-amber)" }}
					>
						{String(RL_HISTORY.length).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">SINCE FIRST PIPELINE</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">SUCCESS RATE</div>
					<div className="rl-stat-value pixel" style={{ color: "var(--lg-ink)" }}>
						{successRate}%
					</div>
					<div className="rl-stat-sub">
						{done} OF {RL_HISTORY.length}
					</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ROWS MIGRATED</div>
					<div className="rl-stat-value pixel" style={{ color: "var(--lg-ink)" }}>
						{totalRows.toLocaleString()}
					</div>
					<div className="rl-stat-sub">ALL RUNS</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ERRORS</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: errors ? "var(--lg-coral)" : "var(--lg-ink-mute)" }}
					>
						{String(errors).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">{errors ? "OPEN" : "NONE"}</div>
				</div>
			</div>

			<div className="rl-section-head">
				<div
					className="pixel"
					style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}
				>
					* ACTIVITY LOG *
				</div>
				<div style={{ display: "flex", gap: 6 }}>
					{(["all", "running", "done", "error"] as const).map((f) => (
						<button
							key={f}
							className={`btn ${filter === f ? "btn-primary" : "btn-ghost"}`}
							style={{ padding: "4px 10px" }}
							onClick={() => setFilter(f)}
							disabled={isEmpty && f !== "all"}
						>
							{f.toUpperCase()}
						</button>
					))}
				</div>
			</div>

			{isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot">
							<SpriteGhost size={80} />
						</div>
						<div className="rl-empty-title">NO RUNS YET</div>
						<div className="rl-empty-sub">
							Pipeline runs show up here with timestamp, stage, rows migrated,
							and status. Run your first pipeline and the ghosts of past
							migrations will appear.
						</div>
					</div>
				</div>
			) : (
				<div className="panel">
					<table className="table">
						<thead>
							<tr>
								<th style={{ width: 90 }}>TIME</th>
								<th style={{ width: 90 }}>DATE</th>
								<th>PROJECT</th>
								<th style={{ width: 110 }}>STAGE</th>
								<th style={{ width: 90 }}>STATUS</th>
								<th style={{ width: 110 }}>ROWS</th>
								<th>NOTE</th>
							</tr>
						</thead>
						<tbody>
							{rows.map((r, i) => (
								<tr key={i}>
									<td
										style={{
											color: "var(--lg-amber)",
											fontFamily: "var(--lg-pixel-tall)",
											fontSize: 15,
										}}
									>
										{r.t}
									</td>
									<td style={{ color: "var(--lg-ink-dim)" }}>{r.d}</td>
									<td>{r.project}</td>
									<td style={{ color: "var(--lg-ink-dim)" }}>{r.stage}</td>
									<td>
										{r.status === "running" && (
											<span className="badge badge-ok">
												<IDot size={6} /> RUN
											</span>
										)}
										{r.status === "done" && (
											<span className="badge badge-solid">DONE</span>
										)}
										{r.status === "error" && (
											<span className="badge badge-err">ERR</span>
										)}
									</td>
									<td style={{ fontVariantNumeric: "tabular-nums" }}>
										{r.rows.toLocaleString()}
									</td>
									<td style={{ color: "var(--lg-ink-dim)" }}>{r.note}</td>
								</tr>
							))}
						</tbody>
					</table>
				</div>
			)}
		</div>
	);
}
