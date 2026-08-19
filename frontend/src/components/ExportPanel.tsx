import { useTranslation } from "react-i18next";
import { useState } from "react";
import {
  fetchExportBlob,
  getRenderExportStatus,
  startRenderExport,
} from "../api/client";
import type { EditorStyle, ExportFormat, StyleParams } from "../types";

interface Props {
  jobId: string;
  style: EditorStyle;
  onToast: (message: string, kind?: "ok" | "error") => void;
}

const POLL_INTERVAL_MS = 3_000;
const RENDER_TIMEOUT_MS = 60 * 60 * 1000;

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
  tagKey: string;
  filename: string;
  render: boolean;
}[] = [
  { format: "srt", tagKey: "srt", filename: "subtitle.srt", render: false },
  { format: "vtt", tagKey: "vtt", filename: "subtitle.vtt", render: false },
  { format: "txt", tagKey: "txt", filename: "subtitle.txt", render: false },
  { format: "ass", tagKey: "ass", filename: "subtitle.ass", render: false },
  { format: "fcpxml", tagKey: "fcpxml", filename: "subtitle.fcpxml", render: false },
  { format: "mp4", tagKey: "mp4", filename: "subtitle.mp4", render: true },
  { format: "webm_alpha", tagKey: "webm", filename: "subtitle-alpha.webm", render: true },
];

export default function ExportPanel({ jobId, style, onToast }: Props) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState<ExportFormat | null>(null);

  const handleDownload = async (format: ExportFormat, filename: string) => {
    if (busy) return;
    setBusy(format);
    try {
      const params = styleToParams(style);
      if (format === "mp4" || format === "webm_alpha") {
        // Burn-in encodes can take minutes: run in the background, poll status,
        // and only download once the cached file is ready.
        let started = await startRenderExport(jobId, format, params);
        const deadline = Date.now() + RENDER_TIMEOUT_MS;
        while (started.status !== "ready") {
          if (Date.now() > deadline) throw new Error(t("exportPanel.renderTimeout"));
          await new Promise((r) => setTimeout(r, POLL_INTERVAL_MS));
          const status = await getRenderExportStatus(jobId, format);
          if (status.status === "failed") {
            throw new Error(status.error || t("exportPanel.failed"));
          }
          if (status.status === "idle") {
            started = await startRenderExport(jobId, format, params);
          } else {
            started = status;
          }
        }
      }
      // all formats go through fetch (with session header) → blob, avoiding <a download> 400s
      const blobUrl = await fetchExportBlob(jobId, format, params);
      const a = document.createElement("a");
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 10_000);
      onToast(format === "mp4" || format === "webm_alpha" ? t("exportPanel.renderDone") : t("exportPanel.exportDone"));
    } catch (e) {
      onToast(e instanceof Error ? e.message : t("exportPanel.failed"), "error");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="card">
      <h2 className="card-title">{t("exportPanel.title")}</h2>
      <div className="export-grid">
        {FORMATS.map(({ format, tagKey, filename, render }) => (
          <button
            key={format}
            className={`export-btn${render ? " render" : ""}${busy === format ? " disabled" : ""}`}
            disabled={busy !== null}
            onClick={() => void handleDownload(format, filename)}
          >
            {busy === format ? (
              <>
                <span className="spinner" aria-hidden="true" />
                {render ? t("exportPanel.rendering") : t("exportPanel.downloading")}
              </>
            ) : (
              <>
                <span className="export-format">
                  {format === "mp4" ? "MP4" : format === "webm_alpha" ? "WEBM" : format.toUpperCase()}
                </span>
                <span>{format === "webm_alpha" ? "WebM" : format.toUpperCase()}</span>
                <span className="export-tag">{t(`exportPanel.${tagKey}`)}</span>
              </>
            )}
          </button>
        ))}
      </div>
      <p className="export-hint">{t("exportPanel.hint")}</p>
    </div>
  );
}
