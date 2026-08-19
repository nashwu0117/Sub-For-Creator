import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getConfig, getJob } from "../api/client";
import { usePolling } from "../hooks/usePolling";
import type { AppConfig, CreateJobResponse, Job, JobStatus, RecentJob } from "../types";
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
    // localStorage unavailable — ignore
  }
}

export default function Home() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [activeJob, setActiveJob] = useState<Job | null>(null);
  const [activeEta, setActiveEta] = useState<number | null>(null);
  const [pollError, setPollError] = useState<string | null>(null);
  const [recentJobs, setRecentJobs] = useState<RecentJob[]>(loadRecentJobs);
  const navigateTimerRef = useRef<number | null>(null);

  const formatRemaining = useCallback(
    (seconds: number): string => {
      const min = Math.floor(seconds / 60);
      const sec = Math.round(seconds % 60);
      if (min <= 0) return t("common.seconds", { count: sec });
      return t("common.minSec", { min, sec });
    },
    [t],
  );

  const formatCreatedAt = useCallback(
    (iso: string): string => {
      try {
        const d = new Date(iso);
        const now = new Date();
        const diffMin = Math.floor((now.getTime() - d.getTime()) / 60000);
        if (diffMin < 1) return t("common.justNow");
        if (diffMin < 60) return t("common.minutesAgo", { count: diffMin });
        const diffH = Math.floor(diffMin / 60);
        if (diffH < 24) return t("common.hoursAgo", { count: diffH });
        return d.toLocaleDateString(i18n.language);
      } catch {
        return "";
      }
    },
    [t, i18n.language],
  );

  useEffect(() => {
    getConfig()
      .then(setConfig)
      .catch((e: unknown) => setConfigError(e instanceof Error ? e.message : t("home.configError", { msg: "" })));
  }, [t]);

  // watching job: poll every 2s while queued / processing
  const watching =
    activeJob !== null && (activeJob.status === "queued" || activeJob.status === "processing");
  const { data: polledJob, error: polledError } = usePolling(
    () => getJob(activeJob!.job_id),
    POLL_INTERVAL,
    watching,
  );

  // polling failure (e.g. 410 expired or temporary disconnect) → show message; cleared on next success
  useEffect(() => {
    setPollError(polledError ? polledError.message : null);
  }, [polledError]);

  const updateRecentStatus = useCallback((jobId: string, status: JobStatus) => {
    setRecentJobs((prev) => {
      const next = prev.map((j) => (j.job_id === jobId ? { ...j, status } : j));
      saveRecentJobs(next);
      return next;
    });
  }, []);

  // poll result updates activeJob; navigate to the editor when done
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

  const handleJobCreated = useCallback((res: CreateJobResponse, filename: string) => {
    const jobId = res.job_id;
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
    setActiveEta(res.eta_seconds);
    // show the status card as queued immediately (polling takes over)
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
      // resume polling with the last known status; polling takes over immediately
      setPollError(null);
      setActiveEta(null);
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
  const noLimits = !config || (config.max_upload_mb <= 0 && config.max_duration_min <= 0 && remaining === null);

  return (
    <>
      <section className="hero">
        <div className="hero-badge">{t("home.badge")}</div>
        <h1>{t("home.title")}</h1>
        <p className="hero-sub">{t("home.sub")}</p>
      </section>

      {config && !noLimits && (
        <div className="limits-banner">
          {config.max_upload_mb > 0 && (
            <span className="limit-item">
              <span className="dot" aria-hidden="true" />
              {t("home.limitUpload", { mb: config.max_upload_mb })}
            </span>
          )}
          {config.max_duration_min > 0 && (
            <span className="limit-item">
              <span className="dot" aria-hidden="true" />
              {t("home.limitDuration", { min: config.max_duration_min })}
            </span>
          )}
          {remaining !== null && (
            <span className={`limit-item${remainingLow ? " warn" : ""}`}>
              <span className="dot" aria-hidden="true" />
              {t("home.limitRemaining", { time: formatRemaining(remaining) })}
            </span>
          )}
        </div>
      )}

      {configError && (
        <div className="error-box" role="alert" aria-live="assertive" style={{ maxWidth: 720, margin: "0 auto var(--space-8)" }}>
          <span>{t("home.configError", { msg: configError })}</span>
        </div>
      )}

      <UploadZone config={config} onJobCreated={handleJobCreated} />

      {activeJob && (
        <>
          <JobStatusCard
            job={activeJob}
            etaSeconds={activeEta}
            onRetry={() => {
              setActiveJob(null);
              setPollError(null);
            }}
          />
          {pollError && (
            <div className="error-box" role="alert">
              <span>{t("home.pollError", { msg: pollError })}</span>
              <button className="btn btn-sm btn-danger" onClick={() => setPollError(null)}>
                {t("common.close")}
              </button>
            </div>
          )}
        </>
      )}

      {recentJobs.length > 0 && (
        <section className="recent-section">
          <h2 className="recent-title">{t("home.recentTitle")}</h2>
          <div className="recent-list">
            {recentJobs.map((job) => (
              <button key={job.job_id} className="recent-item" onClick={() => handleRecentClick(job)}>
                <span className={`status-chip ${job.status}`}>
                  <span className="status-dot" aria-hidden="true" />
                  {job.status === "queued" && t("home.queued")}
                  {job.status === "processing" && t("home.processing")}
                  {job.status === "done" && t("home.done")}
                  {job.status === "failed" && t("home.failed")}
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