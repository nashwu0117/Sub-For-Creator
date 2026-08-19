import { useCallback, useEffect, useRef, useState } from "react";
import { getFonts, uploadFont } from "../api/client";
import type { EditorStyle, FontItem } from "../types";

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

export default function FontSettings({ style, onChange }: Props) {
  const [fonts, setFonts] = useState<FontItem[]>([]);
  const [listError, setListError] = useState<string | null>(null);
  const [selected, setSelected] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const res = await getFonts();
      setFonts(res.fonts);
      setListError(null);
    } catch (e) {
      setListError(e instanceof Error ? e.message : "無法載入字型列表");
    }
  }, []);

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
      setUploadError(e instanceof Error ? e.message : "字型上傳失敗");
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="style-section">
      <h3 className="style-section-title">自訂字型</h3>
      <div className="inline-row">
        <input
          ref={fileInputRef}
          className="text-input"
          type="file"
          accept=".ttf,.otf"
          aria-label="選擇字型檔案"
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
          {uploading ? "上傳中…" : "上傳字型"}
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

      {fonts.length > 0 && (
        <ul className="font-list">
          {fonts.map((f) => (
            <li key={f.filename} className="font-item">
              <span className="font-name">{f.name}</span>
              <span className="font-size">{formatBytes(f.size)}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="field">
        <label className="field-label" htmlFor="font-family-select">
          字型
        </label>
        <select
          id="font-family-select"
          className="select-input"
          value={style.fontFamily ?? DEFAULT_FONT_VALUE}
          onChange={(e) => onChange({ ...style, fontFamily: e.target.value || undefined })}
        >
          <option value={DEFAULT_FONT_VALUE}>預設 (Noto Sans CJK TC)</option>
          {fonts.map((f) => (
            <option key={f.filename} value={f.name}>
              {f.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
