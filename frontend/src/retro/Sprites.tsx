/* Pixel-art mascots with idle animations (bob + blink).
   Two characters only — the CRT monitor and the little ghost. */

import mascotLoadSrc from "../assets/mascots/load.png";
import mascotDeploySrc from "../assets/mascots/deploy.png";

type SpriteProps = { size?: number };

export function MascotLoad({ size = 140 }: SpriteProps) {
	return (
		<img
			src={mascotLoadSrc}
			alt=""
			aria-hidden
			className="sp sp-bob-slow rl-mascot-img"
			style={{ height: size, width: "auto" }}
		/>
	);
}

export function MascotDeploy({ size = 120 }: SpriteProps) {
	return (
		<img
			src={mascotDeploySrc}
			alt=""
			aria-hidden
			className="sp sp-bob rl-mascot-img"
			style={{ height: size, width: "auto" }}
		/>
	);
}

export function SpriteMonitor({ size = 64 }: SpriteProps) {
	return (
		<svg
			className="sp sp-bob sp-bob-slow"
			width={size}
			height={(size / 16) * 14}
			viewBox="0 0 16 14"
			shapeRendering="crispEdges"
			aria-hidden
		>
			<g fill="var(--lg-amber-dim)">
				<rect x="0" y="0" width="16" height="11" />
			</g>
			<g fill="var(--lg-bg)">
				<rect x="2" y="2" width="12" height="7" />
			</g>
			<g fill="var(--lg-amber)">
				<rect x="5" y="11" width="6" height="1" />
				<rect x="3" y="12" width="10" height="1" />
				<rect x="2" y="13" width="12" height="1" />
			</g>
			<g className="sp-eye" fill="var(--lg-amber)">
				<rect x="5" y="4" width="1" height="2" />
				<rect x="10" y="4" width="1" height="2" />
			</g>
			<g fill="var(--lg-amber)">
				<rect x="5" y="7" width="6" height="1" />
				<rect x="5" y="6" width="1" height="1" />
				<rect x="10" y="6" width="1" height="1" />
			</g>
		</svg>
	);
}

export function SpriteGhost({
	size = 64,
	color = "coral",
}: SpriteProps & { color?: "coral" | "amber" }) {
	const body = color === "amber" ? "var(--lg-amber-dim)" : "var(--lg-coral)";
	return (
		<svg
			className="sp sp-bob"
			width={(size / 12) * 14}
			height={(size / 12) * 14}
			viewBox="0 0 12 14"
			shapeRendering="crispEdges"
			aria-hidden
		>
			<g fill={body}>
				<rect x="3" y="0" width="6" height="1" />
				<rect x="2" y="1" width="8" height="1" />
				<rect x="1" y="2" width="10" height="1" />
				<rect x="0" y="3" width="12" height="9" />
				<rect x="0" y="12" width="2" height="1" />
				<rect x="3" y="12" width="2" height="1" />
				<rect x="6" y="12" width="2" height="1" />
				<rect x="9" y="12" width="2" height="1" />
				<rect x="0" y="13" width="1" height="1" />
				<rect x="4" y="13" width="1" height="1" />
				<rect x="7" y="13" width="1" height="1" />
				<rect x="11" y="13" width="1" height="1" />
			</g>
			<g className="sp-eye" fill="var(--lg-bg)">
				<rect x="3" y="5" width="2" height="3" />
				<rect x="7" y="5" width="2" height="3" />
			</g>
			<g fill="var(--lg-ink)">
				<rect x="3" y="5" width="1" height="1" />
				<rect x="7" y="5" width="1" height="1" />
			</g>
		</svg>
	);
}

export function Sparkles() {
	return (
		<div className="sp-sparkles" aria-hidden>
			<span className="sp-spark" style={{ left: "10%", top: "20%", animationDelay: "0s" }} />
			<span className="sp-spark" style={{ left: "85%", top: "30%", animationDelay: "0.6s" }} />
			<span className="sp-spark" style={{ left: "70%", top: "70%", animationDelay: "1.2s" }} />
			<span className="sp-spark" style={{ left: "20%", top: "80%", animationDelay: "1.8s" }} />
			<span className="sp-spark" style={{ left: "50%", top: "10%", animationDelay: "2.4s" }} />
		</div>
	);
}
