/* Pixel-art mascot used by the login screen. The CRT monitor + sparkles
   are the only sprites still in use after the theme rework. */

type SpriteProps = { size?: number };

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
			<g fill="var(--lg-magenta-d)">
				<rect x="0" y="0" width="16" height="11" />
			</g>
			<g fill="var(--lg-bg)">
				<rect x="2" y="2" width="12" height="7" />
			</g>
			<g fill="var(--lg-magenta)">
				<rect x="5" y="11" width="6" height="1" />
				<rect x="3" y="12" width="10" height="1" />
				<rect x="2" y="13" width="12" height="1" />
			</g>
			<g className="sp-eye" fill="var(--lg-magenta)">
				<rect x="5" y="4" width="1" height="2" />
				<rect x="10" y="4" width="1" height="2" />
			</g>
			<g fill="var(--lg-magenta)">
				<rect x="5" y="7" width="6" height="1" />
				<rect x="5" y="6" width="1" height="1" />
				<rect x="10" y="6" width="1" height="1" />
			</g>
		</svg>
	);
}

export function Sparkles() {
	return (
		<div className="sp-sparkles" aria-hidden>
			<span className="sp-spark" style={{ left: '10%', top: '20%', animationDelay: '0s' }} />
			<span className="sp-spark" style={{ left: '85%', top: '30%', animationDelay: '0.6s' }} />
			<span className="sp-spark" style={{ left: '70%', top: '70%', animationDelay: '1.2s' }} />
			<span className="sp-spark" style={{ left: '20%', top: '80%', animationDelay: '1.8s' }} />
			<span className="sp-spark" style={{ left: '50%', top: '10%', animationDelay: '2.4s' }} />
		</div>
	);
}
