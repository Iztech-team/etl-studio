import { PipelineProvider, usePipeline } from "./store/pipeline";
import { ProgressSteps, FloatingPixels } from "./components/ui";
import BackgroundBoxes from "./components/ui/BackgroundBoxes";
import { Separator } from "@/components/ui/8bit/separator";
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
			{/* Background: canvas grid + vignette */}
			<BackgroundBoxes />

			{/* Decorative overlays — all pointer-events-none */}
			<div className="crt-overlay" />
			<div className="absolute inset-0 pointer-events-none z-0 overflow-hidden">
				<div className="background-arcade-lines" />
				<div className="background-arcade-orb background-arcade-orb-1" />
				<div className="background-arcade-orb background-arcade-orb-2" />
				<div className="background-arcade-orb background-arcade-orb-3" />
			</div>
			<FloatingPixels />

			{/* Content — above all background layers */}
			<header className="sticky top-0 z-10 bg-background/80 backdrop-blur-sm">
				<div className="max-w-5xl mx-auto px-6 py-4">
					<div className="flex items-center justify-between mb-4">
						<div className="flex items-center gap-3">
							<span className="text-primary retro text-xs opacity-40 hidden sm:inline">
								{">"}_
							</span>
							<h1 className="text-lg retro text-primary tracking-tight glow">
								ETL Studio
							</h1>
							<span className="text-[9px] retro text-muted-foreground/40 hidden sm:inline">
								v1.0
							</span>
						</div>
						{state.sessionId && (
							<span className="text-[10px] retro text-muted-foreground">
								session:{" "}
								<span className="text-primary/60">
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
				<Separator />
			</header>

			<main className="flex-1 max-w-5xl mx-auto w-full px-6 py-8 relative z-[5]">
				<PhaseComponent />
			</main>

			<Separator />
			<footer className="py-3 text-center relative z-[5]">
				<span className="text-[10px] text-muted-foreground/40 retro">
					{"// "}ETL Studio{" // "}Data Pipeline Toolkit{" //"}
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
