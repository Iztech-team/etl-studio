import type { ReactNode } from 'react';

type IconProps = { size?: number };

const PX = ({ children, size = 12 }: IconProps & { children: ReactNode }) => (
	<svg
		width={size}
		height={size}
		viewBox="0 0 12 12"
		shapeRendering="crispEdges"
		fill="currentColor"
	>
		{children}
	</svg>
);

export const IDisk = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="1" y="1" width="10" height="10" />
		<rect x="3" y="3" width="6" height="3" fill="var(--lg-bg-1)" />
		<rect x="4" y="7" width="4" height="3" fill="var(--lg-bg-1)" />
	</PX>
);

export const IFolder = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="1" y="3" width="10" height="8" />
		<rect x="1" y="2" width="5" height="1" />
		<rect x="2" y="5" width="8" height="1" fill="var(--lg-bg-1)" />
	</PX>
);

export const IClock = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="2" y="1" width="8" height="1" />
		<rect x="1" y="2" width="1" height="8" />
		<rect x="10" y="2" width="1" height="8" />
		<rect x="2" y="10" width="8" height="1" />
		<rect x="5" y="3" width="1" height="3" />
		<rect x="6" y="6" width="3" height="1" />
	</PX>
);

export const IArrow = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="1" y="5" width="8" height="2" />
		<rect x="7" y="3" width="2" height="2" />
		<rect x="9" y="5" width="2" height="2" />
		<rect x="7" y="7" width="2" height="2" />
	</PX>
);

export const ICheck = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="1" y="5" width="2" height="2" />
		<rect x="3" y="7" width="2" height="2" />
		<rect x="5" y="5" width="2" height="2" />
		<rect x="7" y="3" width="2" height="2" />
		<rect x="9" y="1" width="2" height="2" />
	</PX>
);

export const IX = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="1" y="1" width="2" height="2" />
		<rect x="9" y="1" width="2" height="2" />
		<rect x="3" y="3" width="2" height="2" />
		<rect x="7" y="3" width="2" height="2" />
		<rect x="5" y="5" width="2" height="2" />
		<rect x="3" y="7" width="2" height="2" />
		<rect x="7" y="7" width="2" height="2" />
		<rect x="1" y="9" width="2" height="2" />
		<rect x="9" y="9" width="2" height="2" />
	</PX>
);

export const IPlus = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="5" y="1" width="2" height="10" />
		<rect x="1" y="5" width="10" height="2" />
	</PX>
);

export const IUpload = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="5" y="1" width="2" height="7" />
		<rect x="3" y="3" width="2" height="2" />
		<rect x="7" y="3" width="2" height="2" />
		<rect x="1" y="9" width="10" height="2" />
	</PX>
);

export const IDownload = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="5" y="1" width="2" height="7" />
		<rect x="3" y="6" width="2" height="2" />
		<rect x="7" y="6" width="2" height="2" />
		<rect x="1" y="9" width="10" height="2" />
	</PX>
);

export const IStar = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="5" y="0" width="2" height="2" />
		<rect x="3" y="2" width="6" height="2" />
		<rect x="1" y="4" width="10" height="2" />
		<rect x="3" y="6" width="2" height="2" />
		<rect x="7" y="6" width="2" height="2" />
		<rect x="2" y="8" width="2" height="2" />
		<rect x="8" y="8" width="2" height="2" />
		<rect x="1" y="10" width="2" height="2" />
		<rect x="9" y="10" width="2" height="2" />
	</PX>
);

export const IKeyboard = ({ size = 12 }: IconProps) => (
	<PX size={size}>
		<rect x="1" y="2" width="10" height="8" />
		<rect x="2" y="3" width="8" height="6" fill="var(--lg-bg-1)" />
		<rect x="3" y="4" width="1" height="1" fill="currentColor" />
		<rect x="5" y="4" width="1" height="1" fill="currentColor" />
		<rect x="7" y="4" width="1" height="1" fill="currentColor" />
		<rect x="3" y="6" width="1" height="1" fill="currentColor" />
		<rect x="5" y="6" width="2" height="1" fill="currentColor" />
		<rect x="8" y="6" width="1" height="1" fill="currentColor" />
	</PX>
);

export const IDot = ({ size = 8, c = 'currentColor' }: { size?: number; c?: string }) => (
	<span
		style={{
			display: 'inline-block',
			width: size,
			height: size,
			background: c,
		}}
	/>
);
