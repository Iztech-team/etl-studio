import { useState } from "react";
import { IKeyboard } from "./icons";

type Binding = { keys: string[]; label: string };
type Group = { title: string; bindings: Binding[] };

function Key({ k }: { k: string }) {
	return (
		<kbd
			style={{
				display: "inline-block",
				fontFamily: "var(--lg-mono)",
				fontSize: 9,
				lineHeight: "16px",
				padding: "0 5px",
				background: "var(--lg-bg-3)",
				border: "1px solid var(--lg-border-br)",
				color: "var(--lg-amber)",
				letterSpacing: 0,
				whiteSpace: "nowrap",
				boxShadow: "0 1px 0 var(--lg-border-br)",
			}}
		>
			{k}
		</kbd>
	);
}

export function CheatSheet({ groups }: { groups: Group[] }) {
	const [open, setOpen] = useState(false);

	return (
		<div style={{ position: "relative" }}>
			<button
				className="btn btn-ghost"
				onClick={() => setOpen((v) => !v)}
				title="Key bindings"
				style={{ padding: "3px 8px", fontSize: 9, display: "flex", alignItems: "center", gap: 5 }}
			>
				<IKeyboard size={10} />
				KEYS
			</button>

			{open && (
				<div
					style={{
						position: "absolute",
						bottom: "calc(100% + 6px)",
						right: 0,
						zIndex: 200,
						background: "var(--lg-bg-1)",
						border: "1px solid var(--lg-border-br)",
						boxShadow: "var(--lg-shadow)",
						padding: "12px 14px",
						minWidth: 260,
						maxWidth: 340,
						display: "flex",
						flexDirection: "column",
						gap: 12,
					}}
				>
					{groups.map((g) => (
						<div key={g.title}>
							<div
								className="pixel"
								style={{
									fontSize: 8,
									color: "var(--lg-amber)",
									letterSpacing: "0.1em",
									marginBottom: 6,
								}}
							>
								{g.title}
							</div>
							<div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
								{g.bindings.map((b) => (
									<div
										key={b.label}
										style={{
											display: "flex",
											justifyContent: "space-between",
											alignItems: "center",
											gap: 12,
										}}
									>
										<span className="mono" style={{ fontSize: 10, color: "var(--lg-ink-dim)" }}>
											{b.label}
										</span>
										<div style={{ display: "flex", gap: 3, flexShrink: 0 }}>
											{b.keys.map((k, i) => (
												<span key={i} style={{ display: "flex", alignItems: "center", gap: 3 }}>
													{i > 0 && (
														<span style={{ fontSize: 9, color: "var(--lg-ink-mute)" }}>/</span>
													)}
													<Key k={k} />
												</span>
											))}
										</div>
									</div>
								))}
							</div>
						</div>
					))}

					<div
						className="mono"
						style={{
							fontSize: 9,
							color: "var(--lg-ink-faint)",
							borderTop: "1px solid var(--lg-border)",
							paddingTop: 8,
						}}
					>
						bindings inactive while typing in an input
					</div>
				</div>
			)}
		</div>
	);
}
