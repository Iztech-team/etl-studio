import { useEffect, useRef, useState } from 'react';
import { IX } from './icons';

export function RlPromptModal({
	title,
	label,
	placeholder,
	confirmText = 'OK',
	onConfirm,
	onCancel,
}: {
	title: string;
	label: string;
	placeholder?: string;
	confirmText?: string;
	onConfirm: (value: string) => void;
	onCancel: () => void;
}) {
	const [value, setValue] = useState('');
	const inputRef = useRef<HTMLInputElement>(null);

	useEffect(() => {
		inputRef.current?.focus();
	}, []);

	const submit = () => {
		if (value.trim()) onConfirm(value.trim());
	};

	return (
		<div
			style={{
				position: 'fixed',
				inset: 0,
				zIndex: 9999,
				background: 'rgba(0,0,0,0.75)',
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				padding: 24,
			}}
			onClick={onCancel}
		>
			<div
				style={{
					background: 'var(--lg-bg)',
					border: '2px solid var(--lg-amber)',
					width: 400,
					maxWidth: '90vw',
				}}
				onClick={(e) => e.stopPropagation()}
			>
				{/* Header */}
				<div
					style={{
						display: 'flex',
						alignItems: 'center',
						justifyContent: 'space-between',
						padding: '10px 14px',
						borderBottom: '1px solid var(--lg-border)',
						background: 'var(--lg-bg-2)',
					}}
				>
					<span
						className="pixel"
						style={{
							fontSize: 11,
							color: 'var(--lg-amber)',
							letterSpacing: '0.1em',
						}}
					>
						{title}
					</span>
					<button
						className="btn btn-ghost"
						style={{ padding: '2px 6px', fontSize: 10 }}
						onClick={onCancel}
					>
						<IX size={10} />
					</button>
				</div>

				{/* Body */}
				<div style={{ padding: '20px 14px' }}>
					<label
						className="pixel"
						style={{
							fontSize: 10,
							color: 'var(--lg-ink-dim)',
							letterSpacing: '0.1em',
							display: 'block',
							marginBottom: 8,
						}}
					>
						{label}
					</label>
					<input
						ref={inputRef}
						type="text"
						className="mono"
						value={value}
						onChange={(e) => setValue(e.target.value)}
						onKeyDown={(e) => {
							if (e.key === 'Enter') submit();
							if (e.key === 'Escape') onCancel();
						}}
						placeholder={placeholder}
						style={{
							width: '100%',
							padding: '8px 10px',
							background: 'var(--lg-bg-2)',
							border: '1px solid var(--lg-border)',
							color: 'var(--lg-ink)',
							fontSize: 13,
							outline: 'none',
							boxSizing: 'border-box',
						}}
					/>
				</div>

				{/* Footer */}
				<div
					style={{
						display: 'flex',
						justifyContent: 'flex-end',
						gap: 8,
						padding: '0 14px 14px',
					}}
				>
					<button
						className="btn btn-ghost"
						style={{ padding: '6px 14px', fontSize: 10 }}
						onClick={onCancel}
					>
						CANCEL
					</button>
					<button
						className="btn btn-primary"
						style={{ padding: '6px 14px', fontSize: 10 }}
						onClick={submit}
						disabled={!value.trim()}
					>
						{confirmText}
					</button>
				</div>
			</div>
		</div>
	);
}
