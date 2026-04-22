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
	| "select"
	| "transform"
	| "map"
	| "export";

export type Stage = { id: StageId; label: string; sub: string };

export const RL_STAGES: Stage[] = [
	{ id: "upload", label: "UPLOAD", sub: "Database file" },
	{ id: "extract", label: "EXTRACT", sub: "Parse tables" },
	{ id: "select", label: "SELECT", sub: "Pick tables" },
	{ id: "transform", label: "TRANSFORM", sub: "Clean columns" },
	{ id: "map", label: "MAP", sub: "Target schema" },
	{ id: "export", label: "EXPORT", sub: "CSV, SQL, JSON" },
];

export type ResumedSession = {
	sessionId: string;
	preview: Record<string, Record<string, unknown>[]>;
	schema: Record<string, Record<string, unknown>>;
	stats: Record<string, { row_count: number }>;
	tables: string[];
	config: Record<string, unknown> | null;
	transform: Record<string, unknown> | null;
	loadResult: Record<string, unknown> | null;
};

export type Template = {
	id: string;
	name: string;
	fields: number | "dynamic";
	used: number;
	desc: string;
};

export type HistoryStatus = "running" | "done" | "error";

export type HistoryRow = {
	t: string;
	d: string;
	project: string;
	stage: string;
	status: HistoryStatus;
	rows: number;
	note: string;
};

export const RL_TEMPLATES: Template[] = [];
export const RL_HISTORY: HistoryRow[] = [];
