import { levelFromXp } from "./data";

// Mirrors the prototype's XPBar from new_theme/retro-legacy.jsx.
// The bar fills relative to the next-level threshold (every 200 XP) so
// it always swings between empty and ~full as the user clears dungeons.
export function XPBar({ value, label = "PLAYER XP" }: { value: number; label?: string }) {
	const lvl = levelFromXp(value);
	const intoLevel = value % 200;
	const pct = Math.min(100, (intoLevel / 200) * 100);
	return (
		<div
			aria-label={label}
			style={{
				display: "flex",
				alignItems: "center",
				gap: 14,
				padding: "10px 16px",
				border: "1px solid var(--lg-border-br)",
				background: "var(--lg-bg-2)",
				minWidth: 360,
			}}
		>
			<span
				className="pixel"
				style={{ fontSize: 12, color: "var(--lg-cyan)", letterSpacing: "0.18em" }}
			>
				LV {String(lvl).padStart(2, "0")}
			</span>
			<div
				style={{
					flex: 1,
					minWidth: 180,
					height: 14,
					background: "var(--lg-bg)",
					border: "1px solid var(--lg-border)",
					position: "relative",
				}}
			>
				<div
					style={{
						width: pct + "%",
						height: "100%",
						background:
							"linear-gradient(90deg, var(--lg-magenta-d), var(--lg-magenta))",
						boxShadow: "0 0 12px rgba(176,102,255,0.6)",
						transition: "width 0.4s ease-out",
					}}
				/>
			</div>
			<span
				className="pixel glow-magenta"
				style={{ fontSize: 12, color: "var(--lg-magenta)", letterSpacing: "0.12em" }}
			>
				{value} XP
			</span>
		</div>
	);
}

// Simple toast for "+N XP · STAGE CLEARED" notifications. Mounted by the
// pages that emit achievements; auto-dismiss is the page's responsibility.
export function RlAchievement({ message }: { message: string }) {
	return (
		<div className="rl-achievement">
			<span className="star" /> <span className="pixel">{message}</span>
		</div>
	);
}
