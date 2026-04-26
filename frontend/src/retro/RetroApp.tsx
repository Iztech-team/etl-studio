import { useEffect, useRef, useState } from "react";
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
	"pre-extract": 1,
	edit: 1,
	configure: 1,
	transform: 2,
	map: 2, // legacy phase — folded into transform; project just lands on transform
	load: 3,
	stats: 3,
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

type ResumeProgress = {
	total: number;
	done: number;
	current: string | null;
	recent: { name: string; rowCount: number }[]; // last few completed
	warm: boolean;
};

async function fetchResumed(
	project: Project,
	onProgress?: (p: ResumeProgress) => void,
): Promise<ResumedSession | null> {
	try {
		const res = await fetch(`/api/projects/${project.id}/resume`, {
			method: "POST",
		});
		if (!res.ok || !res.body) return null;
		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		let final: ResumedSession | null = null;

		const progress: ResumeProgress = {
			total: 0,
			done: 0,
			current: null,
			recent: [],
			warm: false,
		};
		const RECENT_LIMIT = 12;

		// eslint-disable-next-line no-constant-condition
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			buffer += decoder.decode(value, { stream: true });
			let nl: number;
			while ((nl = buffer.indexOf("\n")) >= 0) {
				const line = buffer.slice(0, nl).trim();
				buffer = buffer.slice(nl + 1);
				if (!line) continue;
				let evt: { event: string; [k: string]: unknown };
				try {
					evt = JSON.parse(line);
				} catch {
					continue;
				}
				if (evt.event === "error") {
					return null;
				}
				if (evt.event === "start") {
					const total = (evt.total as number | undefined) ?? 0;
					if (total > 0) progress.total = total;
					if (evt.warm) progress.warm = true;
					if (onProgress) onProgress({ ...progress });
				} else if (evt.event === "table_done") {
					const name = String(evt.name ?? "");
					const rowCount = (evt.rowCount as number | undefined) ?? 0;
					progress.done += 1;
					progress.current = name;
					progress.recent = [
						...progress.recent.slice(-(RECENT_LIMIT - 1)),
						{ name, rowCount },
					];
					if (onProgress) onProgress({ ...progress });
				} else if (evt.event === "done") {
					final = {
						sessionId: String(evt.session_id ?? ""),
						preview: (evt.preview as ResumedSession["preview"]) ?? {},
						schema: (evt.inferred_schema as ResumedSession["schema"]) ?? {},
						stats: (evt.stats as ResumedSession["stats"]) ?? {},
						tables: Object.keys((evt.preview as Record<string, unknown>) ?? {}),
						config: (evt.config as ResumedSession["config"]) ?? null,
						transform:
							(evt.transform as ResumedSession["transform"]) ?? null,
						loadResult:
							(evt.load_result as ResumedSession["loadResult"]) ?? null,
					};
				}
			}
		}
		return final;
	} catch {
		return null;
	}
}

function ResumeLoadingSplash({
	projectName,
	progress,
}: {
	projectName: string;
	progress: ResumeProgress | null;
}) {
	const tableLogRef = useRef<HTMLDivElement | null>(null);

	useEffect(() => {
		if (tableLogRef.current) {
			tableLogRef.current.scrollTop = tableLogRef.current.scrollHeight;
		}
	}, [progress?.recent.length]);

	const total = progress?.total ?? 0;
	const done = progress?.done ?? 0;
	const pct = total > 0 ? Math.round((done / total) * 100) : 0;
	const recent = progress?.recent ?? [];

	return (
		<div
			style={{
				minHeight: "60vh",
				display: "flex",
				flexDirection: "column",
				alignItems: "center",
				justifyContent: "center",
				gap: 16,
				padding: 24,
			}}
		>
			<div className="sprite-disk" />
			<div
				className="pixel"
				style={{
					fontSize: 14,
					color: "var(--lg-amber)",
					letterSpacing: "0.15em",
				}}
			>
				LOADING PROJECT
			</div>
			<div
				className="mono"
				style={{
					fontSize: 11,
					color: "var(--lg-ink-mute)",
				}}
			>
				{projectName}
			</div>

			{total > 0 && (
				<>
					<div
						className="mono"
						style={{
							fontSize: 12,
							color: "var(--lg-ink)",
							fontVariantNumeric: "tabular-nums",
						}}
					>
						<span style={{ color: "var(--lg-amber)" }}>{done}</span>
						<span style={{ color: "var(--lg-ink-mute)" }}> / {total} tables</span>
						<span style={{ color: "var(--lg-ink-mute)", marginLeft: 8 }}>
							· {pct}%
						</span>
					</div>
					<div
						style={{
							width: "min(560px, 80vw)",
							height: 6,
							background: "var(--lg-bg-1, #222)",
							border: "1px solid var(--lg-border, #333)",
							position: "relative",
							overflow: "hidden",
						}}
					>
						<div
							style={{
								position: "absolute",
								top: 0,
								bottom: 0,
								left: 0,
								width: `${pct}%`,
								background: "var(--lg-amber, #ffb347)",
								transition: "width 120ms linear",
							}}
						/>
					</div>
				</>
			)}

			{recent.length > 0 && (
				<div
					ref={tableLogRef}
					style={{
						width: "min(560px, 80vw)",
						maxHeight: 220,
						overflowY: "auto",
						fontFamily: "var(--lg-mono)",
						fontSize: 11,
						display: "flex",
						flexDirection: "column",
						gap: 2,
						padding: 10,
						background: "var(--lg-bg-1, #1c1711)",
						border: "1px solid var(--lg-border, #3a2a18)",
					}}
				>
					{recent.map((t, i) => (
						<div
							key={`${t.name}-${i}`}
							style={{
								display: "flex",
								gap: 6,
								alignItems: "center",
							}}
						>
							<span style={{ color: "var(--lg-amber)" }}>✓</span>
							<span
								style={{
									flex: 1,
									color: "var(--lg-ink)",
									overflow: "hidden",
									textOverflow: "ellipsis",
									whiteSpace: "nowrap",
								}}
								title={t.name}
							>
								{t.name}
							</span>
							<span
								style={{
									color: "var(--lg-ink-mute)",
									fontVariantNumeric: "tabular-nums",
								}}
							>
								{t.rowCount.toLocaleString()}
							</span>
						</div>
					))}
				</div>
			)}

			{progress?.warm && (
				<div
					className="mono"
					style={{ fontSize: 10, color: "var(--lg-ink-mute)" }}
				>
					(restoring from cache)
				</div>
			)}
		</div>
	);
}

function Shell() {
	const { user } = useAuth();
	const [route, setRoute] = useState<Route>(loadRoute);
	const [stage, setStage] = useState<StageId>(loadStage);
	const [showNewModal, setShowNewModal] = useState(false);
	// True until we've re-hydrated a pipeline route restored from localStorage.
	// The persisted route may carry a stale session_id (the backend's in-memory
	// sessions dict is wiped on every restart, and on a browser refresh we get
	// a fresh React tree but the same stale localStorage). Until we've
	// re-resumed, hide the pipeline so we don't render stale data and 404 on
	// every backend call.
	const [hydrating, setHydrating] = useState<boolean>(
		() => loadRoute().view === "pipeline",
	);
	const [resumeProgress, setResumeProgress] = useState<ResumeProgress | null>(
		null,
	);

	const prevUser = useRef(user);
	useEffect(() => {
		if (!prevUser.current && user) {
			setRoute({ view: "projects" });
			setStage("upload");
		}
		prevUser.current = user;
	}, [user]);

	// One-shot rehydrate on mount. If the persisted route is a pipeline view,
	// re-fetch the project metadata + resume its state so the session_id is
	// fresh and any pipeline progress made before the refresh is restored.
	useEffect(() => {
		if (route.view !== "pipeline") {
			setHydrating(false);
			return;
		}
		const projectId = route.project?.id;
		if (!projectId) {
			setHydrating(false);
			return;
		}
		let cancelled = false;
		(async () => {
			try {
				const projRes = await fetch(`/api/projects/${projectId}`);
				if (!projRes.ok) {
					if (!cancelled) setRoute({ view: "projects" });
					return;
				}
				const project = (await projRes.json()) as Project;
				const resumed = await fetchResumed(project, (p) => {
					if (!cancelled) setResumeProgress(p);
				});
				if (cancelled) return;
				const idx = PHASE_TO_STAGE[project.phase] ?? 0;
				setStage(RL_STAGES[idx].id);
				setRoute({ view: "pipeline", project, resumed });
			} catch {
				if (!cancelled) setRoute({ view: "projects" });
			} finally {
				if (!cancelled) {
					setHydrating(false);
					setResumeProgress(null);
				}
			}
		})();
		return () => {
			cancelled = true;
		};
		// Run once on mount, regardless of route changes.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, []);

	useEffect(() => {
		localStorage.setItem(LS_ROUTE, JSON.stringify(route));
	}, [route]);
	useEffect(() => {
		localStorage.setItem(LS_STAGE, stage);
	}, [stage]);

	if (!user) return <LoginScreen />;

	const open = async (p: Project) => {
		// Navigate to the pipeline view immediately so the user gets visual
		// feedback even when the resume call is slow. The first time a
		// 257-table project is opened after a server restart the resume
		// can take ~50s while CSVs are re-parsed; without an immediate
		// route change the projects page just appears frozen and clicks
		// look like they did nothing.
		const idx = PHASE_TO_STAGE[p.phase] ?? 0;
		setStage(RL_STAGES[idx].id);
		setRoute({ view: "pipeline", project: p, resumed: null });
		setHydrating(true);
		setResumeProgress(null);
		try {
			const resumed = await fetchResumed(p, (prog) => setResumeProgress(prog));
			setRoute({ view: "pipeline", project: p, resumed });
		} finally {
			setHydrating(false);
			setResumeProgress(null);
		}
	};

	const openNew = () => {
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
					{route.view === "pipeline" &&
						(hydrating ? (
							<ResumeLoadingSplash
								projectName={route.project?.name ?? ""}
								progress={resumeProgress}
							/>
						) : (
							<RlPipeline
								project={route.project}
								resumed={route.resumed}
								stage={stage}
								setStage={setStage}
								onBack={() => setRoute({ view: "projects" })}
							/>
						))}
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
