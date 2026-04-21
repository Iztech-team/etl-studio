import { PipelineProvider, usePipeline } from "./store/pipeline";
import { ProgressSteps } from "./components/ui";
import LiquidEther from "./components/ui/LiquidEther";
import { Separator } from "@/components/ui/separator";
import UploadPhase from "./components/UploadPhase";
import ConfigurePhase from "./components/ConfigurePhase";
import ValidatePhase from "./components/ValidatePhase";
import TransformPhase from "./components/TransformPhase";
import LoadPhase from "./components/LoadPhase";
import StatsPhase from "./components/StatsPhase";
import type { Phase } from "./store/pipeline";

const PHASE_COMPONENTS: Record<Phase, () => JSX.Element> = {
	upload: UploadPhase,
	configure: ConfigurePhase,
	validate: ValidatePhase,
	transform: TransformPhase,
	load: LoadPhase,
	stats: StatsPhase,
};

function PipelineApp() {
	const { state, dispatch } = usePipeline();
	const PhaseComponent = PHASE_COMPONENTS[state.phase];

	return (
		<div className="min-h-screen flex flex-col relative">
			<div className="pointer-events-none fixed inset-0 z-[1]">
				<LiquidEther
					colors={["#1E3A8A", "#3B82F6", "#60A5FA"]}
					mouseForce={50}
					cursorSize={150}
					resolution={0.5}
					isBounce={true}
					autoDemo={true}
					autoSpeed={1.4}
					autoIntensity={5.0}
					takeoverDuration={0.2}
					autoResumeDelay={1500}
					autoRampDuration={0.4}
				/>
			</div>
			<div className="pointer-events-none fixed inset-0 z-[2] bg-background/50" />

			<header className="sticky top-0 z-10 bg-background/80 backdrop-blur-sm border-b border-border">
				<div className="max-w-5xl mx-auto px-6 py-4">
					<div className="flex items-center justify-between mb-4">
						<div className="flex items-center gap-3">
							<span className="inline-flex items-center justify-center w-8 h-8 rounded-md bg-primary text-primary-foreground text-sm font-bold">
								E
							</span>
							<h1 className="text-lg font-bold text-foreground tracking-tight">
								ETL Studio
							</h1>
							<span className="text-xs text-muted-foreground hidden sm:inline">
								v1.0
							</span>
						</div>
						{state.sessionId && (
							<span className="text-xs text-muted-foreground">
								session:{" "}
								<span className="text-accent font-mono">
									{state.sessionId.slice(0, 8)}
								</span>
							</span>
						)}
					</div>
					<ProgressSteps
						current={state.phase}
						onNavigate={(phase) => dispatch({ type: "GO_TO_PHASE", phase })}
					/>
				</div>
			</header>

			<main className="flex-1 max-w-5xl mx-auto w-full px-6 py-8 relative z-[5]">
				<PhaseComponent />
			</main>

			<Separator />
			<footer className="py-3 text-center relative z-[5]">
				<span className="text-xs text-muted-foreground">
					ETL Studio · Data Pipeline Toolkit
				</span>
			</footer>
		</div>
	);
}

export default function App() {
	return (
		<PipelineProvider>
			<PipelineApp />
		</PipelineProvider>
	);
}
