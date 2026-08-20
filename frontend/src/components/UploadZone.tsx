import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import { createJob } from "../api/client";
import type { AppConfig, CreateJobResponse } from "../types";

interface Props {
  config: AppConfig | null;
  onJobCreated: (res: CreateJobResponse, filename: string) => void;
}

const DEFAULT_TIERS = ["lite", "standard", "pro"];

function tierLabelKey(tier: string): string {
  return `uploadZone.tier${tier.charAt(0).toUpperCase()}${tier.slice(1)}`;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function UploadZone({ config, onJobCreated }: Props) {
  const { t } = useTranslation();
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [language, setLanguage] = useState("auto");
  const [tier, setTier] = useState<string>(config?.default_options.tier ?? "standard");
  const [llmCorrection, setLlmCorrection] = useState<boolean>(
    config?.default_options.llm_correction_enabled ?? false,
  );
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // config 載入後以伺服器預設值初始化
  useEffect(() => {
    if (!config) return;
    setTier(config.default_options.tier);
    setLlmCorrection(config.default_options.llm_correction_enabled);
  }, [config]);

  const validate = useCallback(
    (f: File): string | null => {
      if (!config || config.max_upload_mb <= 0) return null;
      const maxBytes = config.max_upload_mb * 1024 * 1024;
      if (f.size > maxBytes) {
        return t("uploadZone.tooLarge", {
          mb: config.max_upload_mb,
          size: formatFileSize(f.size),
        });
      }
      return null;
    },
    [config, t],
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
              tier,
              ...(config.llm_available ? { llm_correction_enabled: llmCorrection } : {}),
            }
          : undefined,
        setProgress,
      );
      onJobCreated(job, file.name);
      setFile(null);
      setProgress(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("uploadZone.uploadFailed"));
    } finally {
      setUploading(false);
    }
  }, [file, language, tier, llmCorrection, uploading, onJobCreated, config, t]);

  const languages = config ? ["auto", ...config.supported_languages] : ["auto"];
  const unlimited = !config || config.max_upload_mb <= 0;
  const llmAvailable = config?.llm_available ?? false;
  const tiers = config?.tiers ?? DEFAULT_TIERS;

  return (
    <div className="upload-section" aria-busy={uploading}>
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
        aria-label={t("uploadZone.aria")}
        aria-describedby="upload-zone-hint"
      >
        <div className="upload-zone-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 16V4" />
            <path d="m6 10 6-6 6 6" />
            <path d="M4 20h16" />
          </svg>
        </div>
        <div className="upload-zone-title">{t("uploadZone.title")}</div>
        <div id="upload-zone-hint" className="upload-zone-hint">
          {t("uploadZone.hint")}
          {config && unlimited
            ? ` · ${t("uploadZone.unlimitedHint")}`
            : config
              ? ` · ${t("uploadZone.limitHint", { mb: config.max_upload_mb, min: config.max_duration_min })}`
              : ""}
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
            <span className="field-label">{t("uploadZone.selected")}</span>
            <span className="file-chip">
              <span className="file-name">{file.name}</span>
              <span className="file-size">{formatFileSize(file.size)}</span>
              <button
                type="button"
                className="file-clear"
                onClick={() => setFile(null)}
                aria-label={t("uploadZone.removeAria")}
                disabled={uploading}
              >
                ×
              </button>
            </span>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="upload-language">
              {t("uploadZone.language")}
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
                  {t(`uploadZone.lang.${code}`)}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label className="field-label" htmlFor="upload-tier">
              {t("uploadZone.tier")}
            </label>
            <select
              id="upload-tier"
              className="select-input"
              value={tier}
              onChange={(e) => setTier(e.target.value)}
              disabled={uploading}
            >
              {tiers.map((code) => (
                <option key={code} value={code}>
                  {t(tierLabelKey(code))}
                </option>
              ))}
            </select>
            <p className="field-hint tier-desc">{t(`uploadZone.tierDescriptions.${tier}`)}</p>
          </div>
          <div className="field">
            <label
              className={`checkbox-label${llmAvailable ? "" : " disabled"}`}
              htmlFor="upload-llm"
            >
              <input
                id="upload-llm"
                type="checkbox"
                checked={llmCorrection}
                onChange={(e) => setLlmCorrection(e.target.checked)}
                disabled={uploading || !llmAvailable}
              />
              <span>{t("uploadZone.llmCorrection")}</span>
            </label>
            <p className={`field-hint${llmAvailable ? "" : " warn"}`}>
              {llmAvailable ? t("uploadZone.llmCorrectionHint") : t("uploadZone.llmUnavailable")}
            </p>
          </div>
          <button type="button" className="btn btn-primary" onClick={() => void handleUpload()} disabled={uploading}>
            {uploading ? (
              <>
                <span className="spinner" aria-hidden="true" />
                {t("uploadZone.uploading")}
              </>
            ) : (
              t("uploadZone.start")
            )}
          </button>
        </div>
      )}

      {uploading && (
        <div className="upload-progress">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${progress}%` }} />
          </div>
          <div className="progress-label">{t("uploadZone.progress", { pct: progress })}</div>
        </div>
      )}

      {error && (
        <div className="error-box" role="alert" aria-live="assertive">
          <span>{error}</span>
          <button className="btn btn-sm btn-danger" onClick={() => setError(null)}>
            {t("common.close")}
          </button>
        </div>
      )}
    </div>
  );
}