import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchDownloadBlob,
  getFonts,
  getSystemFontUrl,
  getUploadedFontUrl,
  uploadFont,
} from "../api/client";
import type { EditorStyle, FontItem, SystemFont } from "../types";

interface Props {
  style: EditorStyle;
  onChange: (style: EditorStyle) => void;
}

const DEFAULT_FONT_VALUE = "";

function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function triggerDownload(blobUrl: string, filename: string): void {
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.setTimeout(() => URL.revokeObjectURL(blobUrl), 10_000);
}

export default function FontSettings({ style, onChange }: Props) {
  const { t } = useTranslation();
  const [fonts, setFonts] = useState<FontItem[]>([]);
  const [systemFonts, setSystemFonts] = useState<SystemFont[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getFonts();
      setFonts(res.fonts);
      setSystemFonts(res.system_fonts.filter((f) => f.available));
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : t("fonts.loadFail"));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const handleUpload = async () => {
    if (!selected || uploading) return;
    setUploading(true);
    setUploadError(null);
    setUploadProgress(0);
    try {
      await uploadFont(selected, setUploadProgress);
      setSelected(null);
      setUploadProgress(0);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await refresh();
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : t("fonts.uploadFail"));
    } finally {
      setUploading(false);
    }
  };

  const handleDownloadFile = async (url: string, filename: string) => {
    setDownloadError(null);
    try {
      triggerDownload(await fetchDownloadBlob(url), filename);
    } catch (e) {
      setDownloadError(e instanceof Error ? e.message : t("fonts.downloadFail"));
    }
  };

  const selectedSystem = style.fontFamily
    ? systemFonts.find((f) => f.family === style.fontFamily) ?? null
    : null;
  const selectedUploaded = style.fontFamily
    ? fonts.find((f) => f.name === style.fontFamily) ?? null
    : null;
  const selectedFontFile = selectedSystem?.filename ?? selectedUploaded?.filename ?? null;

  return (
    <div className="style-section">
      <h3 className="style-section-title">{t("fonts.title")}</h3>
      <div className="inline-row">
        <input
          ref={fileInputRef}
          className="text-input"
          type="file"
          accept=".ttf,.otf"
          aria-label={t("fonts.chooseAria")}
          disabled={uploading}
          onChange={(e) => {
            setSelected(e.target.files?.[0] ?? null);
            setUploadError(null);
          }}
        />
        <button
          className="btn btn-sm"
          onClick={() => void handleUpload()}
          disabled={!selected || uploading}
        >
          {uploading ? t("fonts.uploading") : t("fonts.upload")}
        </button>
      </div>

      {uploading && (
        <div className="field">
          <div className="progress-track">
            <div className="progress-fill" style={{ width: `${uploadProgress}%` }} />
          </div>
          <p className="progress-label">{uploadProgress}%</p>
        </div>
      )}

      {(uploadError || listError) && (
        <div className="error-box">{uploadError ?? listError}</div>
      )}
      {downloadError && <div className="error-box">{downloadError}</div>}

      <div className="field">
        <label className="field-label" htmlFor="font-family-select">
          {t("fonts.family")}
        </label>
        <div className="inline-row">
          <select
            id="font-family-select"
            className="select-input"
            value={style.fontFamily ?? DEFAULT_FONT_VALUE}
            onChange={(e) => onChange({ ...style, fontFamily: e.target.value || undefined })}
          >
            <option value={DEFAULT_FONT_VALUE}>{t("fonts.defaultFont")}</option>
            {systemFonts.map((f) => (
              <option key={`sys-${f.family}`} value={f.family}>
                {f.name}
              </option>
            ))}
            {fonts.map((f) => (
              <option key={f.filename} value={f.name}>
                {f.name}
              </option>
            ))}
          </select>
          <button
            className="btn btn-sm"
            onClick={() => {
              if (!selectedFontFile) return;
              const url = selectedSystem
                ? getSystemFontUrl(selectedSystem.filename)
                : getUploadedFontUrl(selectedUploaded!.filename);
              void handleDownloadFile(url, selectedFontFile);
            }}
            disabled={!selectedFontFile}
          >
            {t("fonts.download")}
          </button>
        </div>
        {selectedSystem && (
          <p className="field-hint">
            {t("fonts.license")}:{" "}
            <a
              href={selectedSystem.license_url}
              target="_blank"
              rel="noreferrer"
              className="inline-link"
            >
              {selectedSystem.license}
            </a>
          </p>
        )}
      </div>

      {systemFonts.length > 0 && (
        <div className="style-subsection">
          <h4 className="style-subsection-title">{t("fonts.systemTitle")}</h4>
          <ul className="font-list">
            {systemFonts.map((f) => (
              <li key={`sys-${f.family}`} className="font-item">
                <span className="font-name">{f.name}</span>
                <span className="font-size">{formatBytes(f.size)}</span>
                <button
                  className="btn btn-sm"
                  onClick={() => void handleDownloadFile(getSystemFontUrl(f.filename), f.filename)}
                >
                  {t("fonts.download")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {fonts.length > 0 && (
        <div className="style-subsection">
          <h4 className="style-subsection-title">{t("fonts.uploadedTitle")}</h4>
          <ul className="font-list">
            {fonts.map((f) => (
              <li key={f.filename} className="font-item">
                <span className="font-name">{f.name}</span>
                <span className="font-size">{formatBytes(f.size)}</span>
                <button
                  className="btn btn-sm"
                  onClick={() => void handleDownloadFile(getUploadedFontUrl(f.filename), f.filename)}
                >
                  {t("fonts.download")}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}