import { createContext, useContext, useState, type ReactNode } from 'react';
import type {
	PipelineCtx,
	StagedFile,
	UploadResult,
	TransformResult,
	LoadResult,
	AuditReport,
} from './types';
import type { ResumedSession } from '../data';

export const PipelineContext = createContext<PipelineCtx | null>(null);

export function usePipelineCtx(): PipelineCtx {
	const ctx = useContext(PipelineContext);
	if (!ctx) throw new Error('PipelineContext not found');
	return ctx;
}

export function PipelineProvider({
	projectId,
	projectName,
	resumed,
	children,
}: {
	projectId: string | null;
	projectName: string | null;
	resumed: ResumedSession | null;
	children: ReactNode;
}) {
	const [staged, setStaged] = useState<StagedFile[]>([]);
	const [uploadResult, setUploadResult] = useState<UploadResult | null>(() => {
		if (!resumed) return null;
		// Prefer the full extracted set so excluded tables remain visible
		// when the user revisits the extract stage.
		const tableNames = resumed.allExtractedTables?.length
			? resumed.allExtractedTables
			: resumed.tables.length > 0
				? resumed.tables
				: Object.keys(resumed.schema);
		if (tableNames.length === 0) return null;
		return {
			sessionId: resumed.sessionId,
			tables: tableNames.map((name) => ({
				name,
				rowCount: resumed.stats[name]?.row_count ?? 0,
				colCount: Object.keys(resumed.schema[name] ?? {}).length,
				columns: Object.keys(resumed.schema[name] ?? {}),
			})),
			preview: resumed.preview as Record<string, Record<string, unknown>[]>,
			schema: resumed.schema,
			stats: resumed.stats,
			excludedTables: resumed.excludedTables ?? [],
			selectedEntities: resumed.selectedEntities ?? [],
		};
	});
	const [transformResult, setTransformResult] = useState<TransformResult | null>(() => {
		if (!resumed?.transform) return null;
		const t = resumed.transform as Record<string, unknown>;
		return {
			ok: (t.ok as boolean) ?? true,
			tables_transformed: (t.tables_transformed as number) ?? 0,
			total_rows: (t.total_rows as number) ?? 0,
			encoding_conversions: (t.encoding_conversions as number) ?? 0,
			type_conversions: (t.type_conversions as number) ?? 0,
			reference_mappings: (t.reference_mappings as number) ?? 0,
			null_normalizations: (t.null_normalizations as number) ?? 0,
			warnings: (t.warnings as string[]) ?? [],
			preview: (t.preview as Record<string, unknown>) ?? {},
			strategy_name: (t.strategy_name as string) ?? null,
			strategy_label: (t.strategy_label as string) ?? null,
			strategy_stats: (t.strategy_stats as Record<string, number>) ?? {},
			output_doctypes: (t.output_doctypes as Record<string, number>) ?? {},
			audit_report: (t.audit_report as AuditReport) ?? null,
			setup_checklist_md: (t.setup_checklist_md as string) ?? null,
		};
	});
	const [loadResult, setLoadResult] = useState<LoadResult | null>(() => {
		if (!resumed?.loadResult) return null;
		const l = resumed.loadResult as Record<string, unknown>;
		return {
			ok: (l.ok as boolean) ?? true,
			output_files: (l.output_files as string[]) ?? [],
			rows_written: (l.rows_written as Record<string, number>) ?? {},
			errors: (l.errors as string[]) ?? [],
		};
	});
	const ctx: PipelineCtx = {
		projectId,
		projectName,
		staged,
		addStaged: (files) => setStaged((prev) => [...prev, ...files]),
		removeStaged: (idx) => setStaged((prev) => prev.filter((_, i) => i !== idx)),
		clearStaged: () => setStaged([]),
		uploadResult,
		setUploadResult,
		transformResult,
		setTransformResult,
		loadResult,
		setLoadResult,
	};
	return <PipelineContext.Provider value={ctx}>{children}</PipelineContext.Provider>;
}
