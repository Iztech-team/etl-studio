import { useState } from "react";
import { RL_TEMPLATES } from "./data";
import { IDisk, IPlus } from "./icons";
import { SpriteGhost, Sparkles } from "./Sprites";
import { RlTopbar } from "./Topbar";

export function RlTemplates() {
	const [sel, setSel] = useState<string | null>(RL_TEMPLATES[0]?.id ?? null);
	const t = RL_TEMPLATES.find((x) => x.id === sel);
	const isEmpty = RL_TEMPLATES.length === 0;

	return (
		<div className="rl-page">
			<RlTopbar
				title="TEMPLATES"
				sub="TARGET SCHEMAS REUSED ACROSS PROJECTS"
				right={
					<button className="btn btn-primary">
						<IPlus size={10} /> NEW TEMPLATE
					</button>
				}
			/>

			{isEmpty ? (
				<div className="panel">
					<div className="rl-empty">
						<Sparkles />
						<div className="rl-empty-mascot">
							<SpriteGhost size={80} color="amber" />
						</div>
						<div className="rl-empty-title">NO TEMPLATES YET</div>
						<div className="rl-empty-sub">
							Templates are reusable target schemas. Save one from any project's
							Map stage and it shows up here, ready to apply to the next pipeline.
						</div>
						<button className="btn btn-primary">
							<IPlus size={10} /> NEW TEMPLATE
						</button>
					</div>
				</div>
			) : (
				<div style={{ display: "grid", gridTemplateColumns: "1fr 420px", gap: 16 }}>
					<div className="rl-tpl-grid">
						{RL_TEMPLATES.map((tp) => {
							const active = tp.id === sel;
							return (
								<div
									key={tp.id}
									className={`rl-tpl ${active ? "active" : ""}`}
									onClick={() => setSel(tp.id)}
								>
									<div style={{ display: "flex", gap: 10, alignItems: "flex-start" }}>
										<IDisk size={14} />
										<div style={{ flex: 1 }}>
											<div
												className="pixel"
												style={{ fontSize: 10, color: "var(--lg-amber)" }}
											>
												{tp.name}
											</div>
											<div
												className="mono"
												style={{
													fontSize: 11,
													color: "var(--lg-ink-dim)",
													marginTop: 4,
												}}
											>
												{tp.desc}
											</div>
										</div>
									</div>
									<div
										style={{
											display: "flex",
											gap: 12,
											marginTop: 12,
											fontFamily: "var(--lg-pixel)",
											fontSize: 8,
											letterSpacing: "0.1em",
											color: "var(--lg-ink-mute)",
										}}
									>
										<span>{tp.fields === "dynamic" ? "DYN FIELDS" : tp.fields + " FIELDS"}</span>
										<span>·</span>
										<span>USED {tp.used}×</span>
									</div>
								</div>
							);
						})}
					</div>

					{t && (
						<div className="panel">
							<div className="panel-head">
								<IDisk size={10} /> TEMPLATE DETAIL
							</div>
							<div className="panel-body">
								<div
									className="pixel"
									style={{ fontSize: 12, color: "var(--lg-amber)", marginBottom: 4 }}
								>
									{t.name}
								</div>
								<div
									className="mono"
									style={{
										fontSize: 11,
										color: "var(--lg-ink-dim)",
										marginBottom: 14,
									}}
								>
									{t.desc}
								</div>
								<dl className="kv">
									<dt>FIELDS</dt>
									<dd>{t.fields === "dynamic" ? "inferred per import" : t.fields}</dd>
									<dt>USED BY</dt>
									<dd>
										{t.used} project{t.used === 1 ? "" : "s"}
									</dd>
								</dl>
								<div style={{ display: "flex", gap: 8, marginTop: 14 }}>
									<button className="btn btn-ghost">EDIT</button>
									<button className="btn btn-ghost">DUPLICATE</button>
									<button className="btn btn-coral">DELETE</button>
								</div>
							</div>
						</div>
					)}
				</div>
			)}
		</div>
	);
}
