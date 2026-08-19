import { useState } from "react";
import { buildExportUrl, fetchExportBlob } from "../api/client";
import type { EditorStyle, ExportFormat, StyleParams } from "../types";

interface Props {
  jobId: string;
  style: EditorStyle;
  onToast: (message: string, kind?: "ok" | "error") => void;
}

function styleToParams(style: EditorStyle): StyleParams {
  return {
    font_size: style.fontSize,
    font_color: style.fontColor,
    outline_color: style.outlineColor,
    font_family: style.fontFamily || undefined,
    karaoke: style.karaoke ? 1 : 0,
    position: style.position,
    fade: style.fade ? 200 : undefined,
  };
}

const TEXT_FORMATS: { format: ExportFormat; label: string; tag: string }[] = [
  { format: "srt", label: "SRT", tag: "字幕檔" },
  { format: "vtt", label: "VTT", tag: "網頁字幕" },
  { format: "txt", label: "純文字", tag: "TXT" },
  { format: "ass", label: "ASS", tag: "進階字幕" },
  { format: "fcpxml", label: "FCPXML", tag: "Final Cut" },
];

const RENDER_FORMATS: { format: ExportFormat; label: string; tag: string; filename: string }[] = [
  { format: "mp4", label: "MP4", tag: "燒錄字幕", filename: "subtitle.mp4" },
  { format: "webm_alpha", label: "WebM", tag: "透明背景", filename: "subtitle-alpha.webm" },
];

export default function ExportPanel({ jobId, style, onToast }: Props) {
  const [rendering, setRendering] = useState<ExportFormat | null>(null);

  const handleRenderDownload = async (format: ExportFormat, filename: string) => {
    if (rendering) return;
    setRendering(format);
    try {
      // 轉檔類可能需等待背景渲染（最長 300 秒），用 fetch 取得 blob 並下載
      const blobUrl = await fetchExportBlob(jobId, format, styleToParams(style));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 10_000);
      onToast("匯出完成，開始下載");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "匯出失敗", "error");
    } finally {
      setRendering(null);
    }
  };

  return (
    <div className="card">
      <h2 className="card-title">匯出</h2>
      <div className="export-grid">
        {TEXT_FORMATS.map(({ format, label, tag }) => (
          <a
            key={format}
            className="export-btn"
            href={buildExportUrl(jobId, format, styleToParams(style))}
            download
          >
            <span className="export-format">{format === "txt" ? "TXT" : format.toUpperCase()}</span>
            <span>{format === "txt" ? "純文字" : label}</span>
            <span style={{ fontSize: 11, color: "var(--text-faint)" }}>{tag}</span>
          </a>
        ))}
        {RENDER_FORMATS.map(({ format, label, tag, filename }) => (
          <button
            key={format}
            className={`export-btn render${rendering === format ? " disabled" : ""}`}
            disabled={rendering !== null}
            onClick={() => void handleRenderDownload(format, filename)}
          >
            {rendering === format ? (
              <>
                <span className="spinner" aria-hidden="true" />
                渲染中…
              </>
            ) : (
              <>
                <span className="export-format">{format === "mp4" ? "MP4" : "WEBM"}</span>
                <span>{label}</span>
                <span style={{ fontSize: 11, color: "var(--text-faint)" }}>{tag}</span>
              </>
            )}
          </button>
        ))}
      </div>
      <p className="export-hint">
        ASS / MP4 / WebM 會套用目前的字幕樣式。轉檔類匯出可能需要等待一段時間（最長 5 分鐘）。
      </p>
    </div>
  );
}