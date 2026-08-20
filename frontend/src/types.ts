/** 單一字幕片段 */
export interface Word {
  text: string;
  start: number;
  end: number;
}

/** 字幕片段 */
export interface Segment {
  id: number;
  start: number;
  end: number;
  text: string;
  words?: Word[];
}

export type JobStatus = "queued" | "processing" | "done" | "failed";

export type JobStage = "extracting" | "transcribing" | "segmenting" | null;

export interface JobMeta {
  filename?: string;
  duration?: number;
  language?: string;
  model_size?: string;
}

/** 作業狀態（GET /api/jobs/{id}） */
export interface Job {
  job_id: string;
  status: JobStatus;
  stage: JobStage;
  progress: number;
  queue_position: number | null;
  error: string | null;
  created_at: string | null;
  expires_at: string | null;
  meta: JobMeta;
}

/** 上傳限制與支援語言（GET /api/config） */
export interface AppConfig {
  max_upload_mb: number;
  max_duration_min: number;
  max_queue: number;
  supported_languages: string[];
  session_remaining_seconds: number;
  /** ASR 精準度等級（如 ["lite", "standard", "pro"]） */
  tiers: string[];
  /** 後端是否已設定 LLM 提供者（Ollama 或 API Key） */
  llm_available: boolean;
  default_options: {
    max_line_chars: number;
    model_size: string;
    tier: string;
    denoise_enabled: boolean;
    loudnorm_enabled: boolean;
    llm_correction_enabled: boolean;
  };
}

/** 建立作業的回應（POST /api/jobs） */
export interface CreateJobResponse {
  job_id: string;
  status: JobStatus;
  queue_position: number | null;
  eta_seconds: number | null;
}

/** 字幕資料（GET /api/jobs/{id}/subtitles） */
export interface SubtitlesResponse {
  job_id: string;
  /** 自動偵測失敗時後端可能回傳 null */
  language: string | null;
  segments: Segment[];
  meta: {
    model_size: string;
    max_line_chars: number;
  };
}

export type ExportFormat = "srt" | "vtt" | "txt" | "ass" | "fcpxml" | "mp4" | "webm_alpha";

/** 匯出樣式參數（ass / mp4 / webm_alpha 適用） */
export interface StyleParams {
  font_size?: number;
  font_color?: string;
  outline_color?: string;
  font_family?: string;
  karaoke?: 0 | 1;
  position?: "bottom" | "top";
  /** 字幕淡入淡出時長（毫秒） */
  fade?: number;
}

/** 編輯器樣式狀態 */
export interface EditorStyle {
  fontSize: number;
  fontColor: string;
  outlineColor: string;
  bold: boolean;
  position: "bottom" | "top";
  karaoke: boolean;
  /** 字幕淡入淡出開關 */
  fade: boolean;
  /** 自訂字型名稱（undefined = 預設字型） */
  fontFamily?: string;
}

/** 已上傳的自訂字型（GET /api/fonts） */
export interface FontItem {
  name: string;
  filename: string;
  size: number;
  uploaded_at: string;
}

/** 內建的免費字型（GET /api/fonts → system_fonts，可直接選用與下載） */
export interface SystemFont {
  name: string;
  family: string;
  filename: string;
  size: number;
  license: string;
  license_url: string;
  available: boolean;
}

/** GET /api/fonts 回應 */
export interface FontsResponse {
  fonts: FontItem[];
  system_fonts: SystemFont[];
}

/** 已儲存的樣式預設（localStorage `sfc_style_presets`） */
export interface StylePreset {
  id: string;
  name: string;
  style: EditorStyle;
}

/** localStorage 中的最近作業 */
export interface RecentJob {
  job_id: string;
  filename: string;
  created_at: string;
  status: JobStatus;
}

/** 帳號使用者（GET /api/auth/me、POST /api/auth/login 等） */
export interface User {
  id: number;
  email: string;
  display_name: string;
  created_at: string | null;
}

/** 作品收藏中 job 的狀態（含已過 48h TTL 被清掉的 "expired"） */
export type WorkJobStatus = JobStatus | "expired";

/** 作品收藏（GET /api/works、POST /api/works/{job_id}） */
export interface Work {
  id: number;
  job_id: string;
  title: string;
  created_at: string | null;
  job: {
    status: WorkJobStatus;
    filename: string | null;
    duration: number | null;
    expires_at: string | null;
  };
}

/** GET /api/works 回應（最新在前） */
export type WorkListResponse = Work[];