export type FileKind = 'csv' | 'tsv' | 'json' | 'sql' | 'xlsx' | 'ib' | 'sqlite' | 'unknown';

export type StagedFile = {
	file: File;
	kind: FileKind;
};

export type ExtractedTable = {
	name: string;
	rowCount: number;
	colCount: number;
	columns: string[];
};

export type UploadResult = {
	sessionId: string;
	tables: ExtractedTable[];
	preview: Record<string, Record<string, unknown>[]>;
	schema: Record<string, Record<string, unknown>>;
	stats: Record<string, { row_count: number }>;
	excludedTables: string[];
	selectedEntities: string[];
};

export type EntityDescriptor = {
	id: string;
	label: string;
	depends_on: string[];
};

export type AuditCheck = {
	label: string;
	expected: number;
	actual: number;
	diff: number;
	status: 'ok' | 'over' | 'short';
};

export type AuditReport = {
	legacy_row_counts: Record<string, number>;
	output_doctype_counts: Record<string, number>;
	preserved: AuditCheck[];
	warnings_count: number;
	errors_count: number;
};

export type TransformResult = {
	ok: boolean;
	tables_transformed: number;
	total_rows: number;
	encoding_conversions: number;
	type_conversions: number;
	reference_mappings: number;
	null_normalizations: number;
	warnings: string[];
	exceptions?: Record<string, unknown[]>;
	preview: Record<string, unknown>;
	strategy_name?: string | null;
	strategy_label?: string | null;
	strategy_stats?: Record<string, number>;
	output_doctypes?: Record<string, number>;
	audit_report?: AuditReport | null;
	setup_checklist_md?: string | null;
};

export type StrategyConfigField = {
	type?: string;
	required?: boolean;
	default?: unknown;
	label?: string;
	help?: string;
};

export type StrategyStats = {
	target_doctypes?: number;
	target_fields?: number;
	source_tables?: number;
	fit_score?: number;
};

export type StrategyDescriptor = {
	name: string;
	label: string;
	description: string;
	config_schema: Record<string, StrategyConfigField>;
	tier?: string;
	kind?: string;
	stats?: StrategyStats;
};

export type LoadResult = {
	ok: boolean;
	output_files: string[];
	rows_written: Record<string, number>;
	errors: string[];
	exceptions_written?: string[];
};

export type PipelineCtx = {
	projectId: string | null;
	projectName: string | null;
	staged: StagedFile[];
	addStaged: (files: StagedFile[]) => void;
	removeStaged: (idx: number) => void;
	clearStaged: () => void;
	uploadResult: UploadResult | null;
	setUploadResult: (r: UploadResult | null) => void;
	transformResult: TransformResult | null;
	setTransformResult: (r: TransformResult | null) => void;
	loadResult: LoadResult | null;
	setLoadResult: (r: LoadResult | null) => void;
};

export type ExtractEvent =
	| { event: 'listing' }
	| { event: 'start'; tables: string[] }
	| { event: 'table_done'; name: string; rows: number; index: number; total: number }
	| { event: 'done'; [k: string]: unknown }
	| { event: 'error'; message: string };

export type DonePayload = {
	session_id: string;
	tables_extracted?: string[];
	preview?: Record<string, Record<string, unknown>[]>;
	inferred_schema?: Record<string, Record<string, unknown>>;
	stats?: Record<string, { row_count: number }>;
};

export type UploadProgress = { loaded: number; total: number };
