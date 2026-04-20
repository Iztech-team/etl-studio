import { useEffect, useRef } from "react";

const CELL_W = 64;
const CELL_H = 32;
const COLS = 60;
const ROWS = 40;
const FADE_MS = 1500;

const SKEW_X_DEG = -48;
const SKEW_Y_DEG = 14;
const SCALE = 0.675;

const COLORS = [
	[125, 211, 252],
	[249, 168, 212],
	[134, 239, 172],
	[253, 224, 71],
	[252, 165, 165],
	[216, 180, 254],
	[147, 197, 253],
	[165, 180, 252],
	[196, 181, 253],
];

const randomColor = () => COLORS[Math.floor(Math.random() * COLORS.length)];

interface LitCell {
	col: number;
	row: number;
	color: number[];
	time: number;
}

// Precompute transform matrix
const tanA = Math.tan((SKEW_X_DEG * Math.PI) / 180);
const tanB = Math.tan((SKEW_Y_DEG * Math.PI) / 180);
const ma = SCALE * (1 + tanA * tanB);
const mb = SCALE * tanB;
const mc = SCALE * tanA;
const md = SCALE;

// Inverse matrix (screen → grid coords)
const det = ma * md - mc * mb;
const invA = md / det;
const invB = -mb / det;
const invC = -mc / det;
const invD = ma / det;

const GRID_W = COLS * CELL_W;
const GRID_H = ROWS * CELL_H;

export default function BackgroundBoxes() {
	const canvasRef = useRef<HTMLCanvasElement>(null);
	const litRef = useRef<LitCell[]>([]);
	const lastCellRef = useRef({ col: -1, row: -1 });
	const staticRef = useRef<HTMLCanvasElement | null>(null);
	const animatingRef = useRef(false);
	const animIdRef = useRef(0);

	useEffect(() => {
		const canvas = canvasRef.current!;
		const ctx = canvas.getContext("2d")!;
		let dpr = window.devicePixelRatio || 1;

		// Offscreen canvas for static grid (drawn once, blitted each frame)
		const offscreen = document.createElement("canvas");
		staticRef.current = offscreen;

		function buildStaticGrid() {
			// Size the offscreen canvas to match
			offscreen.width = canvas.width;
			offscreen.height = canvas.height;
			const sctx = offscreen.getContext("2d")!;

			sctx.setTransform(
				ma * dpr, mb * dpr,
				mc * dpr, md * dpr,
				offscreen.width / 2, offscreen.height / 2,
			);

			const ox = -GRID_W / 2;
			const oy = -GRID_H / 2;

			// Grid lines — single path, single stroke
			sctx.strokeStyle = "rgba(71, 85, 105, 0.45)";
			sctx.lineWidth = 0.5;
			sctx.beginPath();
			for (let r = 0; r <= ROWS; r++) {
				const y = oy + r * CELL_H;
				sctx.moveTo(ox, y);
				sctx.lineTo(ox + GRID_W, y);
			}
			for (let c = 0; c <= COLS; c++) {
				const x = ox + c * CELL_W;
				sctx.moveTo(x, oy);
				sctx.lineTo(x, oy + GRID_H);
			}
			sctx.stroke();

			// Plus signs — all in one path, one stroke call
			sctx.strokeStyle = "rgba(71, 85, 105, 0.7)";
			sctx.lineWidth = 1.2;
			sctx.beginPath();
			const ps = 5;
			for (let r = 0; r <= ROWS; r += 2) {
				for (let c = 0; c <= COLS; c += 2) {
					const px = ox + c * CELL_W;
					const py = oy + r * CELL_H;
					sctx.moveTo(px, py - ps);
					sctx.lineTo(px, py + ps);
					sctx.moveTo(px - ps, py);
					sctx.lineTo(px + ps, py);
				}
			}
			sctx.stroke();
		}

		function resize() {
			dpr = window.devicePixelRatio || 1;
			canvas.width = window.innerWidth * dpr;
			canvas.height = window.innerHeight * dpr;
			canvas.style.width = window.innerWidth + "px";
			canvas.style.height = window.innerHeight + "px";
			buildStaticGrid();
		}
		resize();
		window.addEventListener("resize", resize);

		function screenToGrid(sx: number, sy: number) {
			const dx = sx - window.innerWidth / 2;
			const dy = sy - window.innerHeight / 2;
			const gx = invA * dx + invC * dy;
			const gy = invB * dx + invD * dy;
			return {
				col: Math.floor((gx + GRID_W / 2) / CELL_W),
				row: Math.floor((gy + GRID_H / 2) / CELL_H),
			};
		}

		function startAnimLoop() {
			if (animatingRef.current) return;
			animatingRef.current = true;
			animIdRef.current = requestAnimationFrame(draw);
		}

		function onMouseMove(e: MouseEvent) {
			const { col, row } = screenToGrid(e.clientX, e.clientY);
			if (
				col >= 0 && col < COLS &&
				row >= 0 && row < ROWS &&
				(col !== lastCellRef.current.col || row !== lastCellRef.current.row)
			) {
				lastCellRef.current = { col, row };
				litRef.current.push({
					col, row,
					color: randomColor(),
					time: performance.now(),
				});
				startAnimLoop();
			}
		}
		document.addEventListener("mousemove", onMouseMove);

		function draw() {
			const now = performance.now();
			const w = canvas.width;
			const h = canvas.height;

			ctx.setTransform(1, 0, 0, 1, 0, 0);
			ctx.clearRect(0, 0, w, h);

			// Draw lit cells
			ctx.setTransform(
				ma * dpr, mb * dpr,
				mc * dpr, md * dpr,
				w / 2, h / 2,
			);

			const ox = -GRID_W / 2;
			const oy = -GRID_H / 2;

			litRef.current = litRef.current.filter((cell) => {
				const elapsed = now - cell.time;
				if (elapsed > FADE_MS) return false;
				const alpha = 0.3 * (1 - elapsed / FADE_MS);
				const [r, g, b] = cell.color;
				ctx.fillStyle = `rgba(${r},${g},${b},${alpha})`;
				ctx.fillRect(
					ox + cell.col * CELL_W,
					oy + cell.row * CELL_H,
					CELL_W, CELL_H,
				);
				return true;
			});

			// Blit static grid on top
			ctx.setTransform(1, 0, 0, 1, 0, 0);
			ctx.drawImage(offscreen, 0, 0);

			// Stop loop when nothing left to animate
			if (litRef.current.length > 0) {
				animIdRef.current = requestAnimationFrame(draw);
			} else {
				animatingRef.current = false;
				// Draw static grid one last time (clean state)
				ctx.clearRect(0, 0, w, h);
				ctx.drawImage(offscreen, 0, 0);
			}
		}

		// Initial static-only draw (no animation loop until mouse moves)
		ctx.setTransform(1, 0, 0, 1, 0, 0);
		ctx.drawImage(offscreen, 0, 0);

		return () => {
			cancelAnimationFrame(animIdRef.current);
			document.removeEventListener("mousemove", onMouseMove);
			window.removeEventListener("resize", resize);
		};
	}, []);

	return (
		<>
			<canvas
				ref={canvasRef}
				className="pointer-events-none fixed inset-0 z-[1]"
			/>
			<div className="pointer-events-none fixed inset-0 z-[2] bg-background [mask-image:radial-gradient(ellipse_at_center,transparent_15%,black_70%)]" />
		</>
	);
}
