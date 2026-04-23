import { useEffect, useState } from "react";
import { type HistoryRow, type HistoryStatus } from "./data";
import { useAuth } from "./Auth";
import { IDot } from "./icons";
import { SpriteGhost, Sparkles } from "./Sprites";
import { RlTopbar } from "./Topbar";

type Filter = "all" | HistoryStatus;

export function RlHistory() {
	const { user } = useAuth();
	const [filter, setFilter] = useState<Filter>("all");
	const [history, setHistory] = useState<HistoryRow[]>([]);
	const [loading, setLoading] = useState(true);

	useEffect(() => {
		if (!user) {
			setHistory([]);
			setLoading(false);
			return;
		}
		setLoading(true);
		fetch(`/api/history?username=${encodeURIComponent(user.username)}`)
			.then((r) => r.json())
			.then((data) => {
				setHistory(data.history ?? []);
				setLoading(false);
			})
			.catch(() => {
				setHistory([]);
				setLoading(false);
			});
	}, [user]);

	const rows = history.filter((r) => filter === "all" || r.status === filter);
	const totalRows = history.reduce((a, r) => a + r.rows, 0);
	const done = history.filter((r) => r.status === "done").length;
	const errors = history.filter((r) => r.status === "error").length;
	const successRate = history.length
		? Math.round((done / history.length) * 100)
		: 0;
	const isEmpty = history.length === 0;

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
					<div className="rl-stat-label pixel">PROJECTS</div>
					<div
						className="rl-stat-value pixel"
						style={{ color: "var(--lg-amber)" }}
					>
						{String(history.length).padStart(2, "0")}
					</div>
					<div className="rl-stat-sub">TOTAL TRACKED</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">SUCCESS RATE</div>
					<div className="rl-stat-value pixel" style={{ color: "var(--lg-ink)" }}>
						{successRate}%
					</div>
					<div className="rl-stat-sub">
						{done} OF {history.length}
					</div>
				</div>
				<div className="panel rl-stat">
					<div className="rl-stat-label pixel">ROWS MIGRATED</div>
					<div className="rl-stat-value pixel" style={{ color: "var(--lg-ink)" }}>
						{totalRows.toLocaleString()}
					</div>
					<div className="rl-stat-sub">ALL PROJECTS</div>
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

			{loading ? (
				<div className="panel" style={{ padding: 40, textAlign: "center" }}>
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
			) : isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot">
							<SpriteGhost size={80} color="amber" />
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
