import { useEffect, useState } from "react";
import "./retro.css";
import { AuthProvider, LoginScreen, useAuth } from "./Auth";
import { RL_STAGES, type Project, type StageId } from "./data";
import { RlDock } from "./Topbar";
import { RlProjects } from "./Projects";
import { RlTemplates } from "./Templates";
import { RlHistory } from "./History";
import { RlPipeline } from "./Pipeline";

type PageId = "projects" | "templates" | "history";

type Route =
	| { view: "projects" }
	| { view: "templates" }
	| { view: "history" }
	| { view: "pipeline"; project: Project | null };

const LS_ROUTE = "retro-legacy.v2.route";
const LS_STAGE = "retro-legacy.v2.stage";

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

	useEffect(() => {
		localStorage.setItem(LS_ROUTE, JSON.stringify(route));
	}, [route]);
	useEffect(() => {
		localStorage.setItem(LS_STAGE, stage);
	}, [stage]);

	if (!user) return <LoginScreen />;

	const open = (p: Project) => {
		const i = Math.max(0, Math.min(5, p.stage - 1));
		setStage(RL_STAGES[i].id);
		setRoute({ view: "pipeline", project: p });
	};
	const openNew = () => {
		setStage("upload");
		setRoute({
			view: "pipeline",
			project: {
				id: "new",
				name: "NEW PROJECT",
				desc: "",
				source: "—",
				target: "—",
				status: "draft",
				stage: 0,
				progress: 0,
				owner: user.displayName,
				updated: "NOW",
			},
		});
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
