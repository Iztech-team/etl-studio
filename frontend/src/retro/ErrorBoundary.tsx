import { Component, type ReactNode } from 'react';

type Props = { children: ReactNode };
type State = { error: Error | null };

export class ErrorBoundary extends Component<Props, State> {
	state: State = { error: null };

	static getDerivedStateFromError(error: Error): State {
		return { error };
	}

	render() {
		if (this.state.error) {
			return (
				<div
					style={{
						minHeight: '100vh',
						display: 'flex',
						flexDirection: 'column',
						alignItems: 'center',
						justifyContent: 'center',
						gap: 16,
						padding: 24,
						fontFamily: 'var(--lg-mono, monospace)',
					}}
				>
					<div style={{ fontSize: 14, color: 'var(--lg-red, #ff4444)', letterSpacing: '0.15em' }}>
						SOMETHING WENT WRONG
					</div>
					<div
						style={{
							fontSize: 11,
							color: 'var(--lg-ink-mute, #888)',
							maxWidth: 480,
							textAlign: 'center',
							wordBreak: 'break-word',
						}}
					>
						{this.state.error.message}
					</div>
					<button className="btn btn-primary" onClick={() => window.location.reload()}>
						RELOAD
					</button>
				</div>
			);
		}
		return this.props.children;
	}
}
