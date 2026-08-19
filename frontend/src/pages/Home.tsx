import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getConfig, getJob } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { AppConfig, Job, JobStatus, RecentJob } from "../types";
import UploadZone from "../components/UploadZone";
import JobStatusCard from "../components/JobStatusCard";

const RECENT_KEY = "sfc_recent_jobs";
const POLL_INTERVAL = 2000;

function loadRecentJobs(): RecentJob[] {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (j): j is RecentJob =>
        typeof j === "object" && j !== null && typeof (j as RecentJob).job_id === "string",
    );
  } catch {
    return [];
  }
}

function saveRecentJobs(jobs: RecentJob[]) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(jobs.slice(0, 10)));
  } catch {
    // localStorage 不可用時忽略
  }
}

function formatRemaining(seconds: number): string {
  const min = Math.floor(seconds / 60);
  const sec = Math.round(seconds % 60);
  if (min <= 0) return `${sec} 秒`;
  return `${min} 分 ${sec} 秒`;
}

function formatCreatedAt(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000);
    if (diffMin < 1) return "剛剛";
    if (diffMin < 60) return `${diffMin} 分鐘前`;
    const diffH = Math.floor(diffMin / 60);
    if (diffH < 24) return `${diffH} 小時前`;
    return d.toLocaleDateString("zh-TW");
  } catch {
    return "";
  }
}

export default function Home() {
  const navigate = useNavigate();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [recentJobs, setRecentJobs] = useState<RecentJob[]>(loadRecentJobs);
  const navigateTimerRef = useRef<number | null>(null);

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e: unknown) => setConfigError(e instanceof Error ? e.message : "無法取得伺服器設定"));
  }, []);

  // 監看中的作業：queued / processing 時每 2 秒輪詢
  const watching =
    activeJob !== null && (activeJob.status === "queued" || activeJob.status === "processing");
  const { data: polledJob } = usePolling(
    () => getJob(activeJob!.job_id),
    POLL_INTERVAL,
    watching,
  );

  const updateRecentStatus = useCallback((jobId: string, status: JobStatus) => {
    setRecentJobs((prev) => {
      const next = prev.map((j) => (j.job_id === jobId ? { ...j, status } : j));
      saveRecentJobs(next);
      return next;
    });
  }, []);

  // 輪詢結果更新 activeJob；done 時導向編輯器
  useEffect(() => {
    if (!polledJob) return;
    setActiveJob(polledJob);
    updateRecentStatus(polledJob.job_id, polledJob.status);
    if (polledJob.status === "done") {
      if (navigateTimerRef.current !== null) window.clearTimeout(navigateTimerRef.current);
      navigateTimerRef.current = window.setTimeout(() => {
        navigate(`/edit/${polledJob.job_id}`);
      }, 500);
    }
  }, [polledJob, navigate, updateRecentStatus]);

  useEffect(() => {
    return () => {
      if (navigateTimerRef.current !== null) window.clearTimeout(navigateTimerRef.current);
    };
  }, []);

  const handleJobCreated = useCallback((jobId: string, filename: string) => {
    const entry: RecentJob = {
      job_id: jobId,
      filename,
      created_at: new Date().toISOString(),
      status: "queued",
    };
    setRecentJobs((prev) => {
      const next = [entry, ...prev.filter((j) => j.job_id !== jobId)];
      saveRecentJobs(next);
      return next;
    });
    // 立即以 queued 狀態顯示狀態卡（輪詢會接手更新）
    setActiveJob({
      job_id: jobId,
      status: "queued",
      stage: null,
      progress: 0,
      queue_position: null,
      error: null,
      created_at: entry.created_at,
      expires_at: "",
      meta: { filename },
    });
  }, []);

  const handleRecentClick = useCallback(
    (job: RecentJob) => {
      if (job.status === "done") {
        navigate(`/edit/${job.job_id}`);
        return;
      }
      // 恢復輪詢：以最近一次已知狀態顯示，輪詢立即接手
      setActiveJob({
        job_id: job.job_id,
        status: job.status,
        stage: null,
        progress: 0,
        queue_position: null,
        error: null,
        created_at: job.created_at,
        expires_at: "",
        meta: { filename: job.filename },
      });
    },
    [navigate],
  );

  const remaining = config?.session_remaining_seconds ?? null;
  const remainingLow = remaining !== null && remaining < 300;

  return (
    <>
      <section className="hero">
        <div className="hero-badge">開源免費 · AI 自動字幕</div>
        <h1>上傳影片，AI 自動產生字幕</h1>
        <p className="hero-sub">
          語音辨識、斷句、線上編輯、一鍵匯出 — 支援 SRT、VTT、ASS、FCPXML、燒錄 MP4 與透明背景 WebM。
        </p>
      </section>

      {config && (
        <div className="limits-banner">
          <span className="limit-item">
            <span className="dot" aria-hidden="true" />
            單檔上限 <strong>{config.max_upload_mb} MB</strong>
          </span>
          <span className="limit-item">
            <span className="dot" aria-hidden="true" />
            最長 <strong>{config.max_duration_min} 分鐘</strong>
          </span>
          <span className={`limit-item${remainingLow ? " warn" : ""}`}>
            <span className="dot" aria-hidden="true" />
            今日剩餘上傳額度 <strong>{formatRemaining(remaining ?? 0)}</strong>
          </span>
        </div>
      )}

      {configError && (
        <div className="error-box" style={{ maxWidth: 720, margin: "0 auto var(--space-8)" }}>
          <span>無法取得伺服器設定：{configError}</span>
        </div>
      )}

      <UploadZone config={config} onJobCreated={handleJobCreated} />

      {activeJob && (
        <JobStatusCard
          job={activeJob}
          onRetry={() => {
            setActiveJob(null);
          }}
        />
      )}

      {recentJobs.length > 0 && (
        <section className="recent-section">
          <h2 className="recent-title">最近作業</h2>
          <div className="recent-list">
            {recentJobs.map((job) => (
              <button key={job.job_id} className="recent-item" onClick={() => handleRecentClick(job)}>
                <span className={`status-chip ${job.status}`}>
                  <span className="status-dot" aria-hidden="true" />
                  {job.status === "queued" && "排隊中"}
                  {job.status === "processing" && "處理中"}
                  {job.status === "done" && "完成"}
                  {job.status === "failed" && "失敗"}
                </span>
                <span className="recent-name">{job.filename}</span>
                <span className="recent-time">{formatCreatedAt(job.created_at)}</span>
              </button>
            ))}
          </div>
        </section>
      )}
    </>
  );
}