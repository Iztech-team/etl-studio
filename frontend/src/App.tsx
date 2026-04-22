import { useState } from "react";
import { PipelineProvider, usePipeline } from "./store/pipeline";
import { ProgressSteps } from "./components/ui";
import LiquidEther from "./components/ui/LiquidEther";
import { Separator } from "@/components/ui/separator";
import PreExtractPhase from "./components/PreExtractPhase";
import UploadPhase from "./components/UploadPhase";
import EditPhase from "./components/EditPhase";
import ConfigurePhase from "./components/ConfigurePhase";
import ValidatePhase from "./components/ValidatePhase";
import TransformPhase from "./components/TransformPhase";
import LoadPhase from "./components/LoadPhase";
import StatsPhase from "./components/StatsPhase";
import LandingPage from "./components/LandingPage";
import { saveProject } from "./api/projects";
import type { Phase } from "./store/pipeline";

const PHASE_COMPONENTS: Record<Phase, () => JSX.Element> = {
	"pre-extract": PreExtractPhase,
	upload: UploadPhase,
	edit: EditPhase,
	configure: ConfigurePhase,
	validate: ValidatePhase,
	transform: TransformPhase,
	load: LoadPhase,
	stats: StatsPhase,
};

const liquidEtherProps = {
	colors: ["#1E3A8A", "#3B82F6", "#60A5FA"] as [string, string, string],
	mouseForce: 50,
	cursorSize: 150,
	resolution: 0.5,
	isBounce: true,
	autoDemo: true,
	autoSpeed: 1.4,
	autoIntensity: 5.0,
	takeoverDuration: 0.2,
	autoResumeDelay: 1500,
	autoRampDuration: 0.4,
};

function PipelineApp() {
	const { state, dispatch } = usePipeline();
	const [saving, setSaving] = useState(false);

	if (state.mode === "landing") {
		return (
			<>
				<div className="pointer-events-none fixed inset-0 z-[1]">
					<LiquidEther {...liquidEtherProps} />
				</div>
				<div className="pointer-events-none fixed inset-0 z-[2] bg-background/60" />
				<LandingPage />
			</>
		);
	}

	const PhaseComponent = PHASE_COMPONENTS[state.phase];

	async function handleSave() {
		if (!state.projectId) return;
		setSaving(true);
		try {
			await saveProject(state.projectId);
		} finally {
			setSaving(false);
		}
	}

	return (
		<div className="min-h-screen flex flex-col relative">
			<div className="pointer-events-none fixed inset-0 z-[1]">
				<LiquidEther {...liquidEtherProps} />
			</div>
			<div className="pointer-events-none fixed inset-0 z-[2] bg-background/60" />

			<header className="sticky top-0 z-10 bg-background/95 backdrop-blur-md border-b border-border">
				<div className="max-w-5xl mx-auto px-6 py-4">
					<div className="flex items-center justify-between mb-4">
						<div className="flex items-center gap-3">
							<span className="inline-flex items-center justify-center w-8 h-8 rounded-md bg-primary text-primary-foreground text-sm font-bold">
								E
							</span>
							<h1 className="text-lg font-bold text-foreground tracking-tight">
								ETL Legacy
							</h1>
							{state.projectName && (
								<span className="text-sm text-accent font-medium">
									/ {state.projectName}
								</span>
							)}
						</div>
						<div className="flex items-center gap-3">
							{state.mode === "project" && (
								<button
									onClick={handleSave}
									disabled={saving}
									className="px-3 py-1.5 rounded-md border border-border text-xs font-medium text-foreground hover:bg-muted/50 disabled:opacity-50"
								>
									{saving ? "Saving..." : "Save"}
								</button>
							)}
							<button
								onClick={() => dispatch({ type: "RESET" })}
								className="px-3 py-1.5 rounded-md border border-border text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50"
							>
								{state.mode === "project"
									? "Back to Projects"
									: "New Session"}
							</button>
							{state.sessionId && state.mode === "guest" && (
								<span className="text-xs text-muted-foreground">
									session:{" "}
									<span className="text-accent font-mono">
										{state.sessionId.slice(0, 8)}
									</span>
								</span>
							)}
						</div>
					</div>
					<ProgressSteps
						current={state.phase}
						onNavigate={(phase) =>
							dispatch({ type: "GO_TO_PHASE", phase })
						}
					/>
				</div>
			</header>

			<main className="flex-1 max-w-5xl mx-auto w-full px-6 py-8 relative z-[5]">
				<PhaseComponent />
			</main>

			<Separator />
			<footer className="py-3 text-center relative z-[5]">
				<span className="text-xs text-muted-foreground">
					ETL Legacy · Data Pipeline Toolkit
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
