import { useKeyboardGrid } from '../keyboard';

export function FormatPicker({
	formats,
	selected,
	onSelect,
}: {
	formats: { id: string; label: string; sub: string }[];
	selected: string;
	onSelect: (id: string) => void;
}) {
	const grid = useKeyboardGrid({
		count: formats.length,
		columns: 1,
		onActivate: (i) => onSelect(formats[i].id),
		initial: Math.max(
			0,
			formats.findIndex((f) => f.id === selected),
		),
	});

	return (
		<div className="panel">
			<div className="panel-head">FORMAT</div>
			<div className="panel-body" style={{ padding: 0 }}>
				{formats.map((f, i) => {
					const k = grid.getItemProps(i);
					return (
						<div
							key={f.id}
							onClick={() => onSelect(f.id)}
							onMouseEnter={k.onMouseEnter}
							className={`rl-fmt-row ${selected === f.id ? 'active' : ''} ${k.className}`}
						>
							<div
								className="pixel"
								style={{
									fontSize: 9,
									color: selected === f.id ? '#0a0410' : 'var(--lg-amber)',
									letterSpacing: '0.1em',
								}}
							>
								{f.label}
							</div>
							<div
								className="mono"
								style={{
									fontSize: 10,
									color: selected === f.id ? '#0a0410' : 'var(--lg-ink-mute)',
									marginTop: 3,
								}}
							>
								{f.sub}
							</div>
						</div>
					);
				})}
			</div>
		</div>
	);
}
