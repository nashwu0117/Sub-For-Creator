import { useState } from "react";
import { fetchExportBlob } from "../api/client";
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

const FORMATS: {
  format: ExportFormat;
  label: string;
  tag: string;
  filename: string;
  render: boolean;
}[] = [
  { format: "srt", label: "SRT", tag: "字幕檔", filename: "subtitle.srt", render: false },
  { format: "vtt", label: "VTT", tag: "網頁字幕", filename: "subtitle.vtt", render: false },
  { format: "txt", label: "TXT", tag: "純文字", filename: "subtitle.txt", render: false },
  { format: "ass", label: "ASS", tag: "進階字幕", filename: "subtitle.ass", render: false },
  { format: "fcpxml", label: "FCPXML", tag: "Final Cut", filename: "subtitle.fcpxml", render: false },
  { format: "mp4", label: "MP4", tag: "燒錄字幕", filename: "subtitle.mp4", render: true },
  { format: "webm_alpha", label: "WebM", tag: "透明背景", filename: "subtitle-alpha.webm", render: true },
];

export default function ExportPanel({ jobId, style, onToast }: Props) {
  const [busy, setBusy] = useState<ExportFormat | null>(null);

  const handleDownload = async (format: ExportFormat, filename: string) => {
    if (busy) return;
    setBusy(format);
    try {
      // 所有格式都經 fetch（帶 session header）→ blob，避免 <a download> 無法帶 header 而 400
      const blobUrl = await fetchExportBlob(jobId, format, styleToParams(style));
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 10_000);
      onToast(format === "mp4" || format === "webm_alpha" ? "渲染完成，開始下載" : "匯出完成，開始下載");
    } catch (e) {
      onToast(e instanceof Error ? e.message : "匯出失敗", "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card">
      <h2 className="card-title">匯出</h2>
      <div className="export-grid">
        {FORMATS.map(({ format, label, tag, filename, render }) => (
          <button
            key={format}
            className={`export-btn${render ? " render" : ""}${busy === format ? " disabled" : ""}`}
            disabled={busy !== null}
            onClick={() => void handleDownload(format, filename)}
          >
            {busy === format ? (
              <>
                <span className="spinner" aria-hidden="true" />
                {render ? "渲染中…" : "下載中…"}
              </>
            ) : (
              <>
                <span className="export-format">
                  {format === "mp4" ? "MP4" : format === "webm_alpha" ? "WEBM" : format.toUpperCase()}
                </span>
                <span>{label}</span>
                <span className="export-tag">{tag}</span>
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
