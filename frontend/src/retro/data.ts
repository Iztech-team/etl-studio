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

export type Stage = { id: StageId; label: string; sub: string };

export const RL_STAGES: Stage[] = [
	{ id: "upload", label: "UPLOAD", sub: "Database file" },
	{ id: "extract", label: "EXTRACT", sub: "Pick tables" },
	{ id: "transform", label: "TRANSFORM", sub: "Clean & map columns" },
	{ id: "export", label: "EXPORT", sub: "CSV, SQL, JSON" },
];

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

