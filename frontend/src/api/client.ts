import type {
  AppConfig,
  CreateJobResponse,
  ExportFormat,
  FontItem,
  FontsResponse,
  Job,
  Segment,
  StyleParams,
  SubtitlesResponse,
  User,
  Work,
} from "../types";
import i18n from "../i18n";

const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? "/api";

const SESSION_KEY = "sfc_session_token";

//: 分片上傳的單片大小（必須遠低於中間代理的單請求上限，如 Codespaces ~16MB）
const CHUNK_SIZE = 8 * 1024 * 1024;

/** Generate a UUID v4 (crypto.randomUUID with manual fallback) */
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

/** Get (or create) the anonymous session token */
export function getSessionToken(): string {
  let token = localStorage.getItem(SESSION_KEY);
  if (!token) {
    token = generateUuid();
    localStorage.setItem(SESSION_KEY, token);
  }
  return token;
}

/** Parse { detail } from an error response, falling back to a status message */
export async function parseError(res: Response): Promise<Error> {
  let detail = i18n.t("errors.requestFailed", { code: res.status });
  try {
    const body: unknown = await res.json();
    if (body && typeof body === "object" && "detail" in body) {
      const d = (body as { detail: unknown }).detail;
      if (typeof d === "string" && d.length > 0) detail = d;
    }
  } catch {
    // non-JSON response, keep the default message
  }
  return new Error(detail);
}

interface RequestOptions {
  method?: string;
  body?: BodyInit;
  /** whether to attach X-Session-Token (default true; health excluded) */
  withToken?: boolean;
}

/** Generic JSON request wrapper */
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

/**
 * fetch with X-Session-Token.
 * <video> / wavesurfer cannot set custom headers, so they fetch a blob URL first.
 */
export function fetchAuthed(input: RequestInfo | URL): Promise<Response> {
  return fetch(input, { headers: { "X-Session-Token": getSessionToken() } });
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
  tier?: string;
  llm_correction_enabled?: boolean;
}

function uploadSingle(
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
        // non-JSON response
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as CreateJobResponse);
      } else {
        const detail =
          body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
            ? ((body as { detail: string }).detail as string)
            : i18n.t("errors.uploadFailed", { code: xhr.status });
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error(i18n.t("errors.network")));
    const form = new FormData();
    form.append("file", file);
    form.append("language", language);
    if (options) form.append("options", JSON.stringify(options));
    xhr.send(form);
  });
}

function uploadChunk(
  uploadId: string,
  index: number,
  data: Blob,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/jobs/uploads/${encodeURIComponent(uploadId)}/chunks`);
    xhr.setRequestHeader("X-Session-Token", getSessionToken());
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
      } else {
        let detail = i18n.t("errors.uploadFailed", { code: xhr.status });
        try {
          const body: unknown = JSON.parse(xhr.responseText);
          if (
            body &&
            typeof body === "object" &&
            "detail" in body &&
            typeof (body as { detail: unknown }).detail === "string"
          ) {
            detail = (body as { detail: string }).detail;
          }
        } catch {
          // non-JSON response
        }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error(i18n.t("errors.network")));
    const form = new FormData();
    form.append("index", String(index));
    form.append("data", data);
    xhr.send(form);
  });
}

/**
 * Chunked upload: start a session, send 8MiB chunks, then complete.
 * Bypasses proxies that cap a single request body (e.g. GitHub Codespaces).
 */
async function uploadChunked(
  file: File,
  language: string,
  options?: CreateJobOptions,
  onProgress?: (percent: number) => void,
): Promise<CreateJobResponse> {
  const initForm = new FormData();
  initForm.append("filename", file.name);
  initForm.append("language", language);
  if (options) initForm.append("options", JSON.stringify(options));
  const { upload_id } = await request<{ upload_id: string }>("/jobs/uploads", {
    method: "POST",
    body: initForm,
  });

  const total = file.size;
  let sent = 0;
  try {
    for (let start = 0; start < total; start += CHUNK_SIZE) {
      const chunk = file.slice(start, Math.min(start + CHUNK_SIZE, total));
      await uploadChunk(upload_id, Math.floor(start / CHUNK_SIZE), chunk);
      sent += chunk.size;
      onProgress?.(Math.round((sent / total) * 100));
    }
    return await request<CreateJobResponse>(`/jobs/uploads/${encodeURIComponent(upload_id)}/complete`, {
      method: "POST",
    });
  } catch (e) {
    try {
      await request(`/jobs/uploads/${encodeURIComponent(upload_id)}`, { method: "DELETE" });
    } catch {
      // best effort cleanup
    }
    throw e;
  }
}

/**
 * Upload a file to create a job. Uses XMLHttpRequest for progress reporting.
 * Large files are split into chunks to stay under proxy request-body caps.
 * Resolves with the 202 response; rejects with an Error (server detail).
 */
export function createJob(
  file: File,
  language: string,
  options?: CreateJobOptions,
  onProgress?: (percent: number) => void,
): Promise<CreateJobResponse> {
  if (file.size > CHUNK_SIZE) {
    return uploadChunked(file, language, options, onProgress);
  }
  return uploadSingle(file, language, options, onProgress);
}

export function getJob(jobId: string): Promise<Job> {
  return request<Job>(`/jobs/${encodeURIComponent(jobId)}`);
}

/** Uploaded custom fonts list + bundled free fonts (GET /api/fonts) */
export function getFonts(): Promise<FontsResponse> {
  return request<FontsResponse>("/fonts");
}

/** GET URL for an uploaded font file (attachment download) */
export function getUploadedFontUrl(filename: string): string {
  return resolveApiUrl(`/fonts/${encodeURIComponent(filename)}`);
}

/** GET URL for a bundled free font file (attachment download) */
export function getSystemFontUrl(filename: string): string {
  return resolveApiUrl(`/fonts/system/${encodeURIComponent(filename)}`);
}

/** Download any font (or other attachment) via fetch + blob, returning an object URL */
export async function fetchDownloadBlob(url: string): Promise<string> {
  const res = await fetch(url, { headers: { "X-Session-Token": getSessionToken() } });
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/**
 * Upload a custom font (POST /api/fonts, multipart).
 * Uses XMLHttpRequest for progress; rejects with an Error (server detail).
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
        // non-JSON response
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as FontItem);
      } else {
        const detail =
          body && typeof body === "object" && "detail" in body && typeof (body as { detail: unknown }).detail === "string"
            ? ((body as { detail: string }).detail as string)
            : i18n.t("errors.uploadFailed", { code: xhr.status });
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error(i18n.t("errors.network")));
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

/**
 * Resolve an API path to an absolute URL: absolute API_BASE is used directly,
 * relative (default /api) is resolved against window.location.origin.
 */
function resolveApiUrl(path: string): string {
  const base = API_BASE.startsWith("http") ? API_BASE : `${window.location.origin}${API_BASE}`;
  const baseWithSlash = base.endsWith("/") ? base : `${base}/`;
  return new URL(path.replace(/^\/+/, ""), baseWithSlash).toString();
}

/** Build an export URL (with style query params); ``suffix`` = "" | "/render" | "/status" */
function buildExportSubUrl(
  jobId: string,
  format: ExportFormat,
  suffix: string,
  style?: StyleParams,
): string {
  const url = new URL(
    resolveApiUrl(`/jobs/${encodeURIComponent(jobId)}/export/${format}${suffix}`),
  );
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

/** Build an export URL (with style query params) */
export function buildExportUrl(jobId: string, format: ExportFormat, style?: StyleParams): string {
  return buildExportSubUrl(jobId, format, "", style);
}

export function getMediaUrl(jobId: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(jobId)}/media`;
}

export function getAudioUrl(jobId: string): string {
  return `${API_BASE}/jobs/${encodeURIComponent(jobId)}/audio`;
}

export interface RenderStatusResponse {
  status: "idle" | "rendering" | "ready" | "failed";
  error?: string;
}

/** Start a background burn-in render (POST .../export/{fmt}/render) */
export async function startRenderExport(
  jobId: string,
  format: ExportFormat,
  style?: StyleParams,
): Promise<RenderStatusResponse> {
  const res = await fetch(buildExportSubUrl(jobId, format, "/render", style), {
    method: "POST",
    headers: { "X-Session-Token": getSessionToken() },
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as RenderStatusResponse;
}

/** Poll the burn-in render progress (GET .../export/{fmt}/status) */
export async function getRenderExportStatus(
  jobId: string,
  format: ExportFormat,
): Promise<RenderStatusResponse> {
  const res = await fetch(buildExportSubUrl(jobId, format, "/status"), {
    headers: { "X-Session-Token": getSessionToken() },
  });
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as RenderStatusResponse;
}

/** Download via fetch (with session header), returning a blob URL for <a> download */
export async function fetchExportBlob(jobId: string, format: ExportFormat, style?: StyleParams): Promise<string> {
  const url = buildExportUrl(jobId, format, style);
  const res = await fetch(url, { headers: { "X-Session-Token": getSessionToken() } });
  if (!res.ok) throw await parseError(res);
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

/* ============================================================
   帳號系統（auth 用 HttpOnly cookie，瀏覽器自動帶）
   ============================================================ */

/** POST /api/auth/register — 建立帳號（409 = email 已註冊，422 = 格式錯誤） */
export function register(email: string, password: string, displayName?: string): Promise<User> {
  return request<User>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password, ...(displayName ? { display_name: displayName } : {}) }),
  });
}

/** POST /api/auth/login — 驗證憑證並設定 session cookie（401 = 憑證錯誤） */
export function login(email: string, password: string): Promise<User> {
  return request<User>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

/** POST /api/auth/logout — 清除 session cookie（未登入也安全） */
export function logout(): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/auth/logout", { method: "POST" });
}

/**
 * GET /api/auth/me — 回傳目前使用者；401（未登入）回傳 null，
 * 其餘錯誤照常拋出。初始載入時 401 是正常狀態，不是錯誤。
 */
export async function getMe(): Promise<User | null> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { "X-Session-Token": getSessionToken() },
  });
  if (res.status === 401) return null;
  if (!res.ok) throw await parseError(res);
  return (await res.json()) as User;
}

/* ============================================================
   作品收藏
   ============================================================ */

/** POST /api/works/{job_id} — 把匿名 job 收藏進使用者作品庫（403 = 非本人 session） */
export function createWork(jobId: string): Promise<Work> {
  return request<Work>(`/works/${encodeURIComponent(jobId)}`, { method: "POST" });
}

/** GET /api/works — 列出目前使用者的作品，最新在前（401 = 未登入） */
export function getWorks(): Promise<Work[]> {
  return request<Work[]>("/works");
}

/** GET /api/works/{work_id} — 單一作品（含即時 job 狀態） */
export function getWork(workId: number): Promise<Work> {
  return request<Work>(`/works/${workId}`);
}

/** DELETE /api/works/{work_id} — 從作品庫移除（job 本身不受影響） */
export function deleteWork(workId: number): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/works/${workId}`, { method: "DELETE" });
}

/* ============================================================
   詞庫（dictionary）
   ============================================================ */

/** GET /api/dictionary — 目前 session 的詞庫詞條 */
export function getDictionary(): Promise<{ terms: string[] }> {
  return request<{ terms: string[] }>("/dictionary");
}

/** POST /api/dictionary — 新增詞條，回傳完整清單與實際新增的詞條 */
export function addDictionaryTerms(terms: string[]): Promise<{ terms: string[]; added: string[] }> {
  return request<{ terms: string[]; added: string[] }>("/dictionary", {
    method: "POST",
    body: JSON.stringify({ terms }),
  });
}

/** DELETE /api/dictionary — 移除單一詞條 */
export function removeDictionaryTerm(term: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>("/dictionary", {
    method: "DELETE",
    body: JSON.stringify({ term }),
  });
}