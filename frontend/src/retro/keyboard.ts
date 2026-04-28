import { useCallback, useEffect, useState } from "react";

// Skip keyboard shortcuts when the user is typing into a text field — no
// one wants their `j` to jump cards while they're naming a project.
function isTypingTarget(target: EventTarget | null): boolean {
	if (!(target instanceof HTMLElement)) return false;
	const tag = target.tagName;
	if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
	if (target.isContentEditable) return true;
	return false;
}

type GridOptions = {
	count: number;
	columns: number;
	onActivate?: (index: number) => void;
	enabled?: boolean;
	// Initial focus index. Defaults to 0.
	initial?: number;
};

/**
 * 2D keyboard navigation across a grid of N items in `columns` columns.
 *
 * Arrow keys + vim hjkl move focus; Enter/Space activate. Returns props
 * to spread onto each item so it can show the focus ring + accept mouse
 * hover that re-syncs the focused index.
 */
export function useKeyboardGrid({
	count,
	columns,
	onActivate,
	enabled = true,
	initial = 0,
}: GridOptions) {
	const [focused, setFocused] = useState(initial);

	// Clamp focused index when the list shrinks (e.g. delete-then-render).
	useEffect(() => {
		if (count === 0) return;
		if (focused >= count) setFocused(count - 1);
		else if (focused < 0) setFocused(0);
	}, [count, focused]);

	useEffect(() => {
		if (!enabled || count === 0) return;
		const onKey = (e: KeyboardEvent) => {
			if (isTypingTarget(e.target)) return;

			const cols = Math.max(1, columns);
			const row = Math.floor(focused / cols);
			const rows = Math.ceil(count / cols);
			let next = focused;

			switch (e.key) {
				case "ArrowLeft":
				case "h":
					next = Math.max(0, focused - 1);
					break;
				case "ArrowRight":
				case "l":
					next = Math.min(count - 1, focused + 1);
					break;
				case "ArrowUp":
				case "k":
					if (row > 0) next = Math.min(count - 1, focused - cols);
					break;
				case "ArrowDown":
				case "j":
					if (row < rows - 1) next = Math.min(count - 1, focused + cols);
					break;
				case "Enter":
				case " ": {
					// Skip if focus is on a real button/link — let its native
					// activation handle it instead of double-firing.
					const t = e.target as HTMLElement | null;
					if (t && (t.tagName === "BUTTON" || t.tagName === "A")) return;
					if (onActivate && focused >= 0 && focused < count) {
						e.preventDefault();
						onActivate(focused);
					}
					return;
				}
				default:
					return;
			}
			if (next !== focused) {
				e.preventDefault();
				setFocused(next);
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [count, columns, focused, onActivate, enabled]);

	// Spread onto each item: gives it the focus marker + lets mouse hover
	// re-sync so keyboard and mouse don't fight each other.
	const getItemProps = useCallback(
		(i: number) => ({
			className: focused === i ? "kb-focus" : "",
			onMouseEnter: () => setFocused(i),
		}),
		[focused],
	);

	return { focused, setFocused, getItemProps };
}

type GlobalKeysOptions = {
	enabled?: boolean;
	// ESC handler — closes modals, navigates back, etc.
	onBack?: () => void;
	// Tab + Shift+Tab cycle through stages. Direction is +1 / -1.
	onTab?: (direction: 1 | -1) => void;
	// Number-key shortcuts: 1..stageCount jump straight to a stage.
	onStageNumber?: (oneBasedIndex: number) => void;
	stageCount?: number;
};

/**
 * Global page-level shortcuts: ESC for back, Tab/Shift+Tab and 1..N for
 * stage switching. Caller wires the actual navigation; this just listens.
 */
export function useGlobalKeys({
	enabled = true,
	onBack,
	onTab,
	onStageNumber,
	stageCount = 0,
}: GlobalKeysOptions) {
	useEffect(() => {
		if (!enabled) return;
		const onKey = (e: KeyboardEvent) => {
			if (isTypingTarget(e.target)) return;

			if (e.key === "Escape") {
				if (onBack) {
					e.preventDefault();
					onBack();
				}
				return;
			}

			if (onTab && e.key === "Tab") {
				e.preventDefault();
				onTab(e.shiftKey ? -1 : 1);
				return;
			}

			if (onStageNumber && stageCount > 0 && /^[1-9]$/.test(e.key)) {
				const n = parseInt(e.key, 10);
				if (n >= 1 && n <= stageCount) {
					e.preventDefault();
					onStageNumber(n);
				}
			}
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [enabled, onBack, onTab, onStageNumber, stageCount]);
}
