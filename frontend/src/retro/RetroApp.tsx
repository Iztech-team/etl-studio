import { useEffect, useState } from "react";
import "./retro.css";
import { AuthProvider, LoginScreen, useAuth } from "./Auth";
import { RL_STAGES, type Project, type ResumedSession, type StageId } from "./data";
import { RlDock } from "./Topbar";
import { RlProjects } from "./Projects";
import { RlTemplates } from "./Templates";
import { RlHistory } from "./History";
import { RlPipeline } from "./Pipeline";
import { RlPromptModal } from "./PromptModal";

type PageId = "projects" | "templates" | "history";

type Route =
	| { view: "projects" }
	| { view: "templates" }
	| { view: "history" }
	| { view: "pipeline"; project: Project | null; resumed: ResumedSession | null };

const LS_ROUTE = "retro-legacy.v2.route";
const LS_STAGE = "retro-legacy.v2.stage";

const PHASE_TO_STAGE: Record<string, number> = {
	upload: 0,
	"pre-extract": 0,
	edit: 1,
	configure: 2,
	transform: 3,
	map: 4,
	load: 5,
	stats: 5,
};

function loadRoute(): Route {
	try {
		const raw = localStorage.getItem(LS_ROUTE);
		if (raw) {
			const parsed = JSON.parse(raw) as Route;
			if (parsed?.view) return parsed;
		}
	} catch {}
	return { view: "projects" };
}

function loadStage(): StageId {
	try {
		const s = localStorage.getItem(LS_STAGE) as StageId | null;
		if (s && RL_STAGES.some((x) => x.id === s)) return s;
	} catch {}
	return "upload";
}

function Shell() {
	const { user } = useAuth();
	const [route, setRoute] = useState<Route>(loadRoute);
	const [stage, setStage] = useState<StageId>(loadStage);
	const [showNewModal, setShowNewModal] = useState(false);

	useEffect(() => {
		localStorage.setItem(LS_ROUTE, JSON.stringify(route));
	}, [route]);
	useEffect(() => {
		localStorage.setItem(LS_STAGE, stage);
	}, [stage]);

	if (!user) return <LoginScreen />;

	const open = async (p: Project) => {
		const idx = PHASE_TO_STAGE[p.phase] ?? 0;
		setStage(RL_STAGES[idx].id);

		// Try to resume existing session from backend
		try {
			const res = await fetch(`/api/projects/${p.id}/resume`, {
				method: "POST",
			});
			if (res.ok) {
				const data = await res.json();
				const resumed: ResumedSession = {
					sessionId: data.session_id,
					preview: data.preview ?? {},
					schema: data.inferred_schema ?? {},
					stats: data.stats ?? {},
					tables: Object.keys(data.preview ?? {}),
					config: data.config ?? null,
					transform: data.transform ?? null,
					loadResult: data.load_result ?? null,
				};
				setRoute({ view: "pipeline", project: p, resumed });
				return;
			}
		} catch {
			// Fall through to open without resumed session
		}
		setRoute({ view: "pipeline", project: p, resumed: null });
	};

	const openNew = () => {
		const isGuest = user.username === "__guest__";

		if (isGuest) {
			setStage("upload");
			setRoute({ view: "pipeline", project: null, resumed: null });
			return;
		}

		setShowNewModal(true);
	};

	const createProject = async (name: string) => {
		setShowNewModal(false);
		try {
			const res = await fetch("/api/projects", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ name, username: user.username }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => null);
				alert(err?.detail || "Failed to create project");
				return;
			}
			const project: Project = await res.json();
			setStage("upload");
			setRoute({ view: "pipeline", project, resumed: null });
		} catch {
			alert("Network error");
		}
	};

	const goPage = (pageId: PageId) => setRoute({ view: pageId });

	const activePage: PageId =
		route.view === "pipeline" ? "projects" : route.view;

	return (
		<div className="legacy-app rl-shell">
			<div className="rl-window">
				<div key={route.view}>
					{route.view === "projects" && (
						<RlProjects onOpen={open} onNew={openNew} />
					)}
					{route.view === "templates" && <RlTemplates />}
					{route.view === "history" && <RlHistory />}
					{route.view === "pipeline" && (
						<RlPipeline
							project={route.project}
							resumed={route.resumed}
							stage={stage}
							setStage={setStage}
							onBack={() => setRoute({ view: "projects" })}
						/>
					)}
				</div>
			</div>
			<RlDock
				activePage={activePage}
				pipelineStage={route.view === "pipeline" ? stage : null}
				onPage={goPage}
			/>
			{showNewModal && (
				<RlPromptModal
					title="NEW PROJECT"
					label="PROJECT NAME"
					placeholder="my-legacy-db"
					confirmText="CREATE"
					onConfirm={createProject}
					onCancel={() => setShowNewModal(false)}
				/>
			)}
		</div>
	);
}

export function RetroApp() {
	return (
		<AuthProvider>
			<Shell />
		</AuthProvider>
	);
}
