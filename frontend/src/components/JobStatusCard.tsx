import type { Job, JobStage } from "../types";

interface Props {
  job: Job;
  onRetry?: () => void;
}

const STAGE_LABELS: Record<Exclude<JobStage, null>, string> = {
  extracting: "音軌處理",
  transcribing: "語音辨識",
  segmenting: "斷句",
};

export default function JobStatusCard({ job, onRetry }: Props) {
  const { status, stage, progress, queue_position, error, meta } = job;
  const filename = meta.filename ?? job.job_id;

  return (
    <div className="card job-card">
      <div className="job-card-header">
        <span className={`status-chip ${status}`}>
          <span className="status-dot" aria-hidden="true" />
          {status === "queued" && "排隊中"}
          {status === "processing" && "處理中"}
          {status === "done" && "處理完成"}
          {status === "failed" && "處理失敗"}
        </span>
        <div style={{ minWidth: 0 }}>
          <div className="job-card-filename">{filename}</div>
          <div className="job-card-meta">
            {meta.language ? `語言：${meta.language} · ` : ""}
            {meta.model_size ? `模型：${meta.model_size}` : ""}
          </div>
        </div>
      </div>

      <div className="job-card-body">
        {status === "queued" && (
          <div className="job-stage-label">
            {queue_position !== null && queue_position > 0
              ? `目前排隊第 ${queue_position} 位`
              : "等待處理中…"}
          </div>
        )}

        {status === "processing" && (
          <>
            <div className="job-stage-label">{stage ? STAGE_LABELS[stage] : "處理中"}</div>
            <div className="progress-track">
              <div className="progress-fill" style={{ width: `${Math.min(100, Math.max(0, progress))}%` }} />
            </div>
            <div className="progress-label">{Math.round(progress)}%</div>
          </>
        )}

        {status === "done" && <div className="job-stage-sub">字幕已產生，即將開啟編輯器…</div>}

        {status === "failed" && (
          <>
            <div className="job-error">{error ?? "處理失敗，請稍後再試"}</div>
            {onRetry && (
              <div>
                <button className="btn btn-sm" onClick={onRetry}>
                  重新上傳
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}