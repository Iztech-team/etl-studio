import { RL_STAGES, type StageId } from "../data";

export function RlStepper({ stage, onStage }: { stage: StageId; onStage: (s: StageId) => void }) {
	const idx = RL_STAGES.findIndex((s) => s.id === stage);
	return (
		<div className="steprail">
			{RL_STAGES.map((s, i) => (
				<div
					key={s.id}
					className={`step ${s.id === stage ? "active" : ""} ${i < idx ? "done" : ""}`}
					onClick={() => onStage(s.id)}
				>
					<div className="num">{i < idx ? "✓" : i + 1}</div>
					<div>
						<div>{s.label}</div>
						<div
							style={{
								fontFamily: "var(--lg-mono)",
								fontSize: 9,
								opacity: 0.7,
								textTransform: "none",
								letterSpacing: 0,
							}}
						>
							{s.sub}
						</div>
					</div>
					<div
						style={{
							marginLeft: "auto",
							fontFamily: "var(--lg-pixel)",
							fontSize: 8,
							color: i < idx ? "var(--lg-lime)" : "var(--lg-ink-mute)",
							letterSpacing: "0.1em",
						}}
					>
						+{s.xp}XP
					</div>
				</div>
			))}
		</div>
	);
}
