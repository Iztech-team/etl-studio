export type ProjectStatus = "running" | "done" | "error" | "draft";

export type Project = {
	id: string;
	name: string;
	username: string;
	phase: string;
	created_at: string;
	updated_at: string;
};

export type StageId =
	| "upload"
	| "extract"
	| "transform"
	| "export";

export type Stage = { id: StageId; label: string; sub: string; xp: number };

export const RL_STAGES: Stage[] = [
	{ id: "upload",    label: "UPLOAD",    sub: "Insert cartridge", xp: 50 },
	{ id: "extract",   label: "EXTRACT",   sub: "Read tables",      xp: 100 },
	{ id: "transform", label: "TRANSFORM", sub: "Pick strategy",    xp: 150 },
	{ id: "export",    label: "EXPORT",    sub: "Ship it",          xp: 100 },
];

// XP earned by a dungeon based on its current backend phase. The phase
// tells us which stages were CLEARED (i.e. moving past upload means
// upload's xp was earned). The pipeline/stats phase = all four cleared.
const PHASE_TO_CLEARED_STAGES: Record<string, number> = {
	upload: 0,
	"pre-extract": 1,
	edit: 1,
	configure: 1,
	transform: 2,
	map: 2,
	load: 3,
	stats: 4,
};

export function phaseEarnedXp(phase: string): number {
	const clearedCount = PHASE_TO_CLEARED_STAGES[phase] ?? 0;
	let xp = 0;
	for (let i = 0; i < clearedCount && i < RL_STAGES.length; i++) {
		xp += RL_STAGES[i].xp;
	}
	return xp;
}

export function levelFromXp(xp: number): number {
	return Math.floor(xp / 200) + 1;
}

export type ResumedSession = {
	sessionId: string;
	preview: Record<string, Record<string, unknown>[]>;
	schema: Record<string, Record<string, unknown>>;
	stats: Record<string, { row_count: number }>;
	tables: string[];
	excludedTables: string[];
	allExtractedTables: string[];
	config: Record<string, unknown> | null;
	transform: Record<string, unknown> | null;
	loadResult: Record<string, unknown> | null;
};

