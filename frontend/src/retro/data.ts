export type ProjectStatus = "running" | "done" | "error" | "draft";

export type Project = {
	id: string;
	name: string;
	desc: string;
	source: string;
	target: string;
	status: ProjectStatus;
	stage: number;
	progress: number;
	owner: string;
	updated: string;
	error?: string;
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
	{ id: "upload", label: "UPLOAD", sub: ".IB file" },
	{ id: "extract", label: "EXTRACT", sub: "Parse tables" },
	{ id: "select", label: "SELECT", sub: "Pick tables" },
	{ id: "transform", label: "TRANSFORM", sub: "Clean columns" },
	{ id: "map", label: "MAP", sub: "Target schema" },
	{ id: "export", label: "EXPORT", sub: "CSV, SQL, JSON" },
];

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

export const RL_PROJECTS: Project[] = [
	{
		id: "p1",
		name: "SALES ARCHIVE 1998",
		desc: "Migrate legacy sales database to Postgres",
		source: "sales_archive.IB",
		target: "postgres://warehouse/sales",
		status: "running",
		stage: 3,
		progress: 48,
		owner: "SYSOP",
		updated: "2H AGO",
	},
];
export const RL_TEMPLATES: Template[] = [];
export const RL_HISTORY: HistoryRow[] = [];
