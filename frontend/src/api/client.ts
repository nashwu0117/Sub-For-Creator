import type {
  AppConfig,
  CreateJobResponse,
  ExportFormat,
  FontItem,
  Job,
  Segment,
  StyleParams,
  SubtitlesResponse,
} from "../types";

const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

const SESSION_KEY = "sfc_session_token";

/** 產生 UUID v4（crypto.randomUUID，不支援時退回手動實作） */
function generateUuid(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

/** 取得（或建立）匿名 session token */
export function getSessionToken(): string {
  let token = localStorage.getItem(SESSION_KEY);
  if (!token) {
    token = generateUuid();
    localStorage.setItem(SESSION_KEY, token);
  }
  return token;
}

/** 從錯誤回應中解析 { detail }，否則回退到狀態碼訊息 */
async function parseError(res: Response): Promise<Error> {
  let detail = `請求失敗（HTTP ${res.status}）`;
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string" && d.length > 0) detail = d;
    }
  } catch {
    // 非 JSON 回應，保留預設訊息
  }
  return new Error(detail);
}

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  /** 是否帶上 X-Session-Token（預設 true；health 除外） */
  withToken?: boolean;
}

/** 通用 JSON 請求包裝 */
async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, withToken = true } = options;
  const headers = new Headers();
  if (withToken) headers.set("X-Session-Token", getSessionToken());
  if (body !== undefined && !(body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${API_BASE}${path}`, { method, headers, body });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as T;
}

export interface HealthResponse {
  status: string;
  version: string;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health", { withToken: false });
}

export function getConfig(): Promise<AppConfig> {
  return request<AppConfig>("/config");
}

export interface CreateJobOptions {
  model_size?: string;
  max_line_chars?: number;
  punctuation_threshold?: number;
}

/**
 * 上傳檔案建立作業（使用 XMLHttpRequest 以取得上傳進度）。
 * 成功時 resolve 202 回應；失敗時 reject Error（含伺服器 detail）。
 */
export function createJob(
  file: File,
  language: string,
  options?: CreateJobOptions,
  onProgress?: (percent: number) => void,
): Promise<CreateJobResponse> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/jobs`);
    xhr.setRequestHeader("X-Session-Token", getSessionToken());
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // 非 JSON 回應
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as CreateJobResponse);
      } else {
        const detail =
          body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
            ? ((body as { detail: string }).detail as string)
            : `上傳失敗（HTTP ${xhr.status}）`;
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("網路錯誤，無法連線伺服器"));
    const form = new FormData();
    form.append("file", file);
    form.append("language", language);
    if (options) form.append("options", JSON.stringify(options));
    xhr.send(form);
  });
}

export function getJob(jobId: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`);
}

/** 已上傳的自訂字型列表（GET /api/fonts，自動帶 session token） */
export function getFonts(): Promise<{ fonts: FontItem[] }> {
  return request<{ fonts: FontItem[] }>("/fonts");
}

/**
 * 上傳自訂字型（POST /api/fonts，multipart）。
 * 使用 XMLHttpRequest 以取得上傳進度；失敗時 reject Error（含伺服器 detail）。
 */
export function uploadFont(file: File, onProgress?: (percent: number) => void): Promise<FontItem> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/fonts`);
    xhr.setRequestHeader("X-Session-Token", getSessionToken());
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) {
        onProgress(Math.round((e.loaded / e.total) * 100));
      }
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // 非 JSON 回應
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as FontItem);
      } else {
        const detail =
          body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
            ? ((body as { detail: string }).detail as string)
            : `上傳失敗（HTTP ${xhr.status}）`;
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("網路錯誤，無法連線伺服器"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function getSubtitles(jobId: string): Promise<SubtitlesResponse> {
  return request<SubtitlesResponse>(`/jobs/${encodeURIComponent(jobId)}/subtitles`);
}

export function putSubtitles(jobId: string, segments: Segment[]): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/jobs/${encodeURIComponent(jobId)}/subtitles`, {
    method: "PUT",
    body: JSON.stringify({ segments }),
  });
}

/** 建立匯出 URL（含樣式 query 參數） */
export function buildExportUrl(jobId: string, format: ExportFormat, style?: StyleParams): string {
  const base = API_BASE.startsWith("http") ? API_BASE : `${window.location.origin}${API_BASE}`;
  const url = new URL(`/jobs/${encodeURIComponent(jobId)}/export/${format}`, base);
  if (style) {
    if (style.font_size !== undefined) url.searchParams.set("font_size", String(style.font_size));
    if (style.font_color) url.searchParams.set("font_color", style.font_color);
    if (style.outline_color) url.searchParams.set("outline_color", style.outline_color);
    if (style.font_family) url.searchParams.set("font_family", style.font_family);
    if (style.karaoke !== undefined) url.searchParams.set("karaoke", String(style.karaoke));
    if (style.position) url.searchParams.set("position", style.position);
    if (typeof style.fade === "number" && style.fade > 0) url.searchParams.set("fade", String(style.fade));
  }
  return url.toString();
}

export function getMediaUrl(jobId: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(jobId)}/media`;
}

export function getAudioUrl(jobId: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(jobId)}/audio`;
}

/** 以 fetch 下載（帶 session header），回傳 blob URL 供 <a> 觸發下載 */
export async function fetchExportBlob(jobId: string, format: ExportFormat, style?: StyleParams): Promise<string> {
  const url = buildExportUrl(jobId, format, style);
  const res = await fetch(url, { headers: { "X-Session-Token": getSessionToken() } });
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}