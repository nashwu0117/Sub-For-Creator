import { useTranslation } from "react-i18next";
import type { Job, JobStage } from "../types";

interface Props {
  job: Job;
  /** estimated wait seconds from the job-creation response (queued only) */
  etaSeconds?: number | null;
  onRetry?: () => void;
}

const STAGE_LABELS: Record<Exclude<JobStage, null>, string> = {
  extracting: "extracting",
  transcribing: "transcribing",
  segmenting: "segmenting",
};

export default function JobStatusCard({ job, etaSeconds, onRetry }: Props) {
  const { t } = useTranslation();
  const { status, stage, progress, queue_position, error, meta } = job;
  const filename = meta.filename ?? job.job_id;

  const formatEta = (seconds: number): string => {
    if (seconds < 60) return t("common.seconds", { count: Math.max(1, Math.round(seconds)) });
    return t("jobStatus.etaMinutes", { count: Math.round(seconds / 60) });
  };

  return (
    <div
      className="card job-card"
      role={status === "failed" ? "alert" : "status"}
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="job-card-header">
        <span className={`status-chip ${status}`}>
          <span className="status-dot" aria-hidden="true" />
          {status === "queued" && t("jobStatus.queued")}
          {status === "processing" && t("jobStatus.processing")}
          {status === "done" && t("jobStatus.done")}
          {status === "failed" && t("jobStatus.failed")}
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="job-card-filename">{filename}</div>
          <div className="job-card-meta">
            {meta.language ? `${t("jobStatus.lang", { lang: meta.language })} · ` : ""}
            {meta.model_size ? t("jobStatus.model", { model: meta.model_size }) : ""}
          </div>
        </div>
      </div>

      <div className="job-card-body">
        {status === "queued" && (
          <div className="job-stage-label">
            {queue_position !== null && queue_position > 0
              ? t("jobStatus.queuePosition", { pos: queue_position })
              : t("jobStatus.waiting")}
            {etaSeconds !== null && etaSeconds !== undefined && etaSeconds > 0 && (
              <span className="job-stage-sub">
                {t("jobStatus.etaSuffix", { eta: formatEta(etaSeconds) })}
              </span>
            )}
          </div>
        )}

        {status === "processing" && (
          <>
            <div className="job-stage-label">{stage ? t(`jobStatus.${STAGE_LABELS[stage]}`) : t("jobStatus.processing")}</div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
            </div>
            <div className="progress-label">{Math.round(progress)}%</div>
          </>
        )}

        {status === "done" && <div className="job-stage-sub">{t("jobStatus.ready")}</div>}

        {status === "failed" && (
          <>
            <div className="job-error">{error ?? t("jobStatus.failedMsg")}</div>
            {onRetry && (
              <div>
                <button className="btn btn-sm" onClick={onRetry}>
                  {t("jobStatus.retry")}
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}