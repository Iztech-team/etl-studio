import axios, { AxiosError } from "axios";
import type {
	UploadResponse,
	ConfigureRequest,
	ConfigureResponse,
	TransformResponse,
	LoadRequest,
	LoadResponse,
	StatsResponse,
	PreExtractResponse,
	TableDataResponse,
	EditDataResponse,
} from "../types/api";

const api = axios.create({ baseURL: "/api" });

api.interceptors.response.use(
	(res) => res,
	(err: AxiosError<{ detail?: string }>) => {
		const message = err.response?.data?.detail ?? err.message;
		return Promise.reject(new Error(message));
	},
);

export async function preExtract(
	file: File,
	password?: string,
	onProgress?: (percent: number) => void,
	projectId?: string,
): Promise<PreExtractResponse> {
	const form = new FormData();
	form.append("file", file);
	if (password) form.append("password", password);
	if (projectId) form.append("project_id", projectId);
	const { data } = await api.post<PreExtractResponse>("/pre-extract", form, {
		onUploadProgress: (e) => {
			if (onProgress && e.total) {
				onProgress(Math.round((e.loaded / e.total) * 100));
			}
		},
	});
	return data;
}

export type PreExtractStreamEvent =
	| { event: "listing" }
	| { event: "start"; tables: string[] }
	| { event: "table_done"; name: string; rows: number; index: number; total: number; csv?: string }
	| { event: "error"; message: string };

export async function preExtractStream(
	file: File,
	password: string | undefined,
	projectId: string | undefined,
	onEvent: (event: PreExtractStreamEvent) => void,
	onUploadProgress?: (percent: number) => void,
): Promise<PreExtractResponse> {
	const form = new FormData();
	form.append("file", file);
	if (password) form.append("password", password);
	if (projectId) form.append("project_id", projectId);

	// The browser fetch() API doesn't expose upload progress. For tracking
	// "uploading vs extracting" we set 100% when the response headers arrive.
	const res = await fetch("/api/pre-extract", { method: "POST", body: form });
	if (onUploadProgress) onUploadProgress(100);
	if (!res.ok || !res.body) {
		const text = await res.text().catch(() => "");
		throw new Error(text || `HTTP ${res.status}`);
	}

	const reader = res.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	let finalPayload: PreExtractResponse | null = null;
	let streamError: string | null = null;

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
			let parsed: unknown;
			try {
				parsed = JSON.parse(line);
			} catch {
				continue;
			}
			const evt = parsed as { event: string; [k: string]: unknown };
			if (evt.event === "error") {
				streamError = String(evt.message ?? "Extraction failed");
				break;
			}
			if (evt.event === "done") {
				const { event: _e, ...rest } = evt;
				finalPayload = rest as unknown as PreExtractResponse;
			} else {
				onEvent(evt as unknown as PreExtractStreamEvent);
			}
		}
		if (streamError) break;
	}

	if (streamError) throw new Error(streamError);
	if (!finalPayload) throw new Error("Stream ended without a final result");
	return finalPayload;
}

export async function preExtractSelect(sessionId: string, tables: string[]): Promise<void> {
	await api.post(`/pre-extract-select/${sessionId}`, { tables });
}

export async function fetchTableData(sessionId: string): Promise<TableDataResponse> {
	const { data } = await api.get<TableDataResponse>(`/table-data/${sessionId}`);
	return data;
}

export async function saveTableData(
	sessionId: string,
	tables: Record<string, Record<string, unknown>[]>,
): Promise<EditDataResponse> {
	const { data } = await api.post<EditDataResponse>(`/table-data/${sessionId}`, { tables });
	return data;
}

export async function uploadFiles(files: File[], projectId?: string): Promise<UploadResponse> {
	const form = new FormData();
	for (const f of files) form.append("files", f);
	if (projectId) form.append("project_id", projectId);
	const { data } = await api.post<UploadResponse>("/upload", form);
	return data;
}

export async function configure(
	sessionId: string,
	config: ConfigureRequest,
): Promise<ConfigureResponse> {
	const { data } = await api.post<ConfigureResponse>(`/configure/${sessionId}`, config);
	return data;
}

export async function transform(sessionId: string): Promise<TransformResponse> {
	const { data } = await api.get<TransformResponse>(`/transform/${sessionId}`);
	return data;
}

export async function load(sessionId: string, config: LoadRequest): Promise<LoadResponse> {
	const { data } = await api.post<LoadResponse>(`/load/${sessionId}`, config);
	return data;
}

export async function fetchStats(sessionId: string): Promise<StatsResponse> {
	const { data } = await api.get<StatsResponse>(`/stats/${sessionId}`);
	return data;
}

export function downloadUrl(sessionId: string, filename: string): string {
	return `/api/download/${sessionId}/${encodeURIComponent(filename)}`;
}
