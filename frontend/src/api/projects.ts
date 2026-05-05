import axios from "axios";
import type { Project, ResumeResponse } from "../types/project";

const api = axios.create({ baseURL: "/api" });

api.interceptors.response.use(
	(res) => res,
	(err) => {
		const message = err.response?.data?.detail ?? err.message;
		return Promise.reject(new Error(message));
	},
);

export async function createProject(name: string, username: string): Promise<Project> {
	const { data } = await api.post<Project>("/projects", { name, username });
	return data;
}

export async function listProjects(username: string): Promise<Project[]> {
	const { data } = await api.get<{ projects: Project[] }>("/projects", { params: { username } });
	return data.projects;
}

export async function renameProject(projectId: string, name: string): Promise<Project> {
	const { data } = await api.patch<Project>(`/projects/${projectId}`, { name });
	return data;
}

export async function deleteProject(projectId: string): Promise<void> {
	await api.delete(`/projects/${projectId}`);
}

export async function resumeProject(projectId: string): Promise<ResumeResponse> {
	const { data } = await api.post<ResumeResponse>(`/projects/${projectId}/resume`);
	return data;
}

export async function saveProject(projectId: string): Promise<void> {
	await api.post(`/projects/${projectId}/save`);
}
