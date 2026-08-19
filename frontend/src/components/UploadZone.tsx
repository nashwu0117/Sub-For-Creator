import { useCallback, useRef, useState } from "react";
import { createJob } from "../api/client";
import type { AppConfig, CreateJobResponse } from "../types";

interface Props {
  config: AppConfig | null;
  onJobCreated: (res: CreateJobResponse, filename: string) => void;
}

const LANGUAGE_NAMES: Record<string, string> = {
  auto: "自動偵測",
  zh: "中文",
  en: "英文",
  ja: "日文",
  ko: "韓文",
  es: "西班牙文",
  fr: "法文",
  de: "德文",
  ru: "俄文",
  pt: "葡萄牙文",
  it: "義大利文",
  th: "泰文",
  vi: "越南文",
  id: "印尼文",
  ar: "阿拉伯文",
  hi: "印度文",
};

function languageLabel(code: string): string {
  return LANGUAGE_NAMES[code] ?? code;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadZone({ config, onJobCreated }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("auto");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const validate = useCallback(
    (f: File): string | null => {
      if (!config) return null;
      const maxBytes = config.max_upload_mb * 1024 * 1024;
      if (f.size > maxBytes) {
        return `檔案超過大小限制（上限 ${config.max_upload_mb} MB，此檔案 ${formatFileSize(f.size)}）`;
      }
      return null;
    },
    [config],
  );

  const pickFile = useCallback(
    (f: File | undefined | null) => {
      if (!f) return;
      const err = validate(f);
      if (err) {
        setError(err);
        return;
      }
      setError(null);
      setFile(f);
    },
    [validate],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      pickFile(e.dataTransfer.files?.[0]);
    },
    [pickFile],
  );

  const handleUpload = useCallback(async () => {
    if (!file || uploading) return;
    setUploading(true);
    setError(null);
    setProgress(0);
    try {
      const job = await createJob(
        file,
        language,
        config
          ? {
              model_size: config.default_options.model_size,
              max_line_chars: config.default_options.max_line_chars,
            }
          : undefined,
        setProgress,
      );
      onJobCreated(job, file.name);
      setFile(null);
      setProgress(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "上傳失敗，請稍後再試");
    } finally {
      setUploading(false);
    }
  }, [file, language, uploading, onJobCreated]);

  const languages = config ? ["auto", ...config.supported_languages] : ["auto"];

  return (
    <div className="upload-section">
      <div
        className={`upload-zone${dragging ? " dragging" : ""}`}
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        aria-label="上傳影片或音檔"
      >
        <div className="upload-zone-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 16V4" />
            <path d="m6 10 6-6 6 6" />
            <path d="M4 20h16" />
          </svg>
        </div>
        <div className="upload-zone-title">拖曳影片或音檔到這裡，或點擊選擇檔案</div>
        <div className="upload-zone-hint">
          支援常見影片與音訊格式
          {config ? ` · 單檔上限 ${config.max_upload_mb} MB · 最長 ${config.max_duration_min} 分鐘` : ""}
        </div>
        <input
          ref={inputRef}
          type="file"
          accept="video/*,audio/*"
          onChange={(e) => {
            pickFile(e.target.files?.[0]);
            e.target.value = "";
          }}
        />
      </div>

      {file && (
        <div className="upload-options">
          <div className="field file-info">
            <span className="field-label">已選擇檔案</span>
            <span className="file-chip">
              <span className="file-name">{file.name}</span>
              <span className="file-size">{formatFileSize(file.size)}</span>
              <button
                type="button"
                className="file-clear"
                onClick={() => setFile(null)}
                aria-label="移除檔案"
                disabled={uploading}
              >
                ×
              </button>
            </span>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="upload-language">
              字幕語言
            </label>
            <select
              id="upload-language"
              className="select-input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={uploading}
            >
              {languages.map((code) => (
                <option key={code} value={code}>
                  {languageLabel(code)}
                </option>
              ))}
            </select>
          </div>
          <button className="btn btn-primary" onClick={() => void handleUpload()} disabled={uploading}>
            {uploading ? (
              <>
                <span className="spinner" aria-hidden="true" />
                上傳中…
              </>
            ) : (
              "開始產生字幕"
            )}
          </button>
        </div>
      )}

      {uploading && (
        <div className="upload-progress">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <div className="progress-label">上傳進度 {progress}%</div>
        </div>
      )}

      {error && (
        <div className="error-box">
          <span>{error}</span>
          <button className="btn btn-sm btn-danger" onClick={() => setError(null)}>
            關閉
          </button>
        </div>
      )}
    </div>
  );
}