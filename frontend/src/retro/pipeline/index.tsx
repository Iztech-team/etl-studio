import { useState } from 'react';
import { RL_STAGES, type Project, type ResumedSession, type StageId } from '../data';
import { RlTopbar } from '../Topbar';
import { RlAchievement } from '../XPBar';
import { useGlobalKeys } from '../keyboard';
import { PipelineProvider } from './context';
import { RlStepper } from './Stepper';
import { RlUpload } from './UploadStage';
import { RlExtract } from './ExtractStage';
import { RlTransform } from './TransformStage';
import { RlExport } from './ExportStage';

export function RlPipeline({
	project,
	resumed,
	stage,
	setStage,
	onBack,
}: {
	project: Project | null;
	resumed: ResumedSession | null;
	stage: StageId;
	setStage: (s: StageId) => void;
	onBack: () => void;
}) {
	const [achievement, setAchievement] = useState<string | null>(null);
	const showAchievement = (msg: string) => {
		setAchievement(msg);
		window.setTimeout(() => setAchievement(null), 2200);
	};

	const next = () => {
		const i = RL_STAGES.findIndex((s) => s.id === stage);
		if (i < 0) return;
		const cleared = RL_STAGES[i];
		showAchievement(`+${cleared.xp} XP · ${cleared.label} CLEARED`);
		if (i < RL_STAGES.length - 1) setStage(RL_STAGES[i + 1].id);
	};
	const stageMeta = RL_STAGES.find((s) => s.id === stage);

	useGlobalKeys({
		onBack: onBack,
		onTab: (dir) => {
			const i = RL_STAGES.findIndex((s) => s.id === stage);
			if (i < 0) return;
			// Wrap around: Tab on the last stage cycles to the first; Shift+Tab
			// on the first cycles to the last.
			const len = RL_STAGES.length;
			const target = (i + dir + len) % len;
			if (target !== i) setStage(RL_STAGES[target].id);
		},
		onStageNumber: (n) => {
			if (n >= 1 && n <= RL_STAGES.length) setStage(RL_STAGES[n - 1].id);
		},
		stageCount: RL_STAGES.length,
	});
	return (
		<PipelineProvider
			projectId={project?.id ?? null}
			projectName={project?.name ?? null}
			resumed={resumed}
		>
			<div className="rl-page">
				<RlTopbar
					title={project?.name?.toUpperCase() || 'PIPELINE'}
					sub={project ? `PHASE: ${project.phase.toUpperCase()}` : 'NOT STARTED'}
					right={
						<button className="btn btn-ghost" onClick={onBack}>
							← DUNGEONS
						</button>
					}
				/>
				<RlStepper stage={stage} onStage={setStage} />
				<div
					className="pixel"
					style={{
						fontSize: 9,
						color: 'var(--lg-ink-mute)',
						letterSpacing: '0.15em',
						margin: '16px 0 4px',
					}}
				>
					[ STAGE {RL_STAGES.findIndex((s) => s.id === stage) + 1}/{RL_STAGES.length} ·{' '}
					{stageMeta?.label} · {stageMeta?.sub.toUpperCase()} ]
				</div>
				<div className="rl-stage" key={stage}>
					{stage === 'upload' && <RlUpload onNext={next} />}
					{stage === 'extract' && <RlExtract onNext={next} />}
					{stage === 'transform' && <RlTransform onNext={next} />}
					{stage === 'export' && <RlExport onDone={onBack} />}
				</div>
				{achievement && <RlAchievement message={achievement} />}
			</div>
		</PipelineProvider>
	);
}
