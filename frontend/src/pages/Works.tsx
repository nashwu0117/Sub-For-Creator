import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { deleteWork, getWorks } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { usePolling } from "../hooks/usePolling";
import type { Work } from "../types";

const POLL_INTERVAL = 5000;

export default function Works() {
  const { t, i18n } = useTranslation();
  const navigate = useNavigate();
  const { user, openAuth, showToast } = useAuth();
  const [works, setWorks] = useState<Work[]>([]);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  // 登入後每 5s 輪詢，反映 job 狀態變化（如 done → expired）
  const { data, error, loading, refresh } = usePolling(() => getWorks(), POLL_INTERVAL, user !== null);

  useEffect(() => {
    if (data) setWorks(data);
  }, [data]);

  const formatCreatedAt = useCallback(
    (iso: string | null): string => {
      if (!iso) return "";
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

  const handleOpen = useCallback(
    (work: Work) => {
      if (work.job.status === "expired") return;
      navigate(`/edit/${work.job_id}`);
    },
    [navigate],
  );

  const handleDelete = useCallback(
    async (work: Work) => {
      if (!window.confirm(t("works.deleteConfirm", { title: work.title }))) return;
      setDeletingId(work.id);
      try {
        await deleteWork(work.id);
        setWorks((prev) => prev.filter((w) => w.id !== work.id));
        showToast(t("works.deleted"));
      } catch (e) {
        showToast(e instanceof Error ? e.message : t("works.deleteFailed", { msg: "" }), "error");
      } finally {
        setDeletingId(null);
      }
    },
    [t, showToast],
  );

  if (!user) {
    return (
      <section className="works-page">
        <h1 className="works-title">{t("works.title")}</h1>
        <div className="works-login-prompt">
          <p>{t("works.loginPrompt")}</p>
          <button className="btn btn-primary" type="button" onClick={() => openAuth("login")}>
            {t("works.loginButton")}
          </button>
        </div>
      </section>
    );
  }

  return (
    <section className="works-page">
      <h1 className="works-title">{t("works.title")}</h1>
      {error && (
        <div className="error-box" role="alert">
          <span>{t("works.loadFailed", { msg: error.message })}</span>
          <button className="btn btn-sm btn-danger" type="button" onClick={() => void refresh()}>
            {t("common.close")}
          </button>
        </div>
      )}
      {loading && works.length === 0 && (
        <div className="works-loading">
          <span className="spinner spinner-dark" aria-hidden="true" />
        </div>
      )}
      {!loading && works.length === 0 && <div className="works-empty">{t("works.empty")}</div>}
      {works.length > 0 && (
        <ul className="works-list">
          {works.map((work) => {
            const expired = work.job.status === "expired";
            return (
              <li key={work.id} className={`works-item${expired ? " is-expired" : ""}`}>
                <button
                  className="works-item-main"
                  type="button"
                  onClick={() => handleOpen(work)}
                  disabled={expired}
                  aria-label={expired ? t("works.expiredHint") : t("works.open", { title: work.title })}
                  title={expired ? t("works.expiredHint") : undefined}
                >
                  <span className={`status-chip ${work.job.status}`}>
                    <span className="status-dot" aria-hidden="true" />
                    {work.job.status === "queued" && t("home.queued")}
                    {work.job.status === "processing" && t("home.processing")}
                    {work.job.status === "done" && t("home.done")}
                    {work.job.status === "failed" && t("home.failed")}
                    {work.job.status === "expired" && t("works.expired")}
                  </span>
                  <span className="works-item-title">{work.title}</span>
                  {work.job.filename && <span className="works-item-filename">{work.job.filename}</span>}
                  <span className="works-item-time">{formatCreatedAt(work.created_at)}</span>
                </button>
                <button
                  className="works-item-delete"
                  type="button"
                  onClick={() => void handleDelete(work)}
                  disabled={deletingId === work.id}
                  aria-label={t("works.deleteAria", { title: work.title })}
                  title={t("works.delete")}
                >
                  <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M2.5 4.5h11M6.5 4.5V3a1 1 0 0 1 1-1h1a1 1 0 0 1 1 1v1.5M4 4.5l.6 8a1.5 1.5 0 0 0 1.5 1.4h3.8a1.5 1.5 0 0 0 1.5-1.4l.6-8M6.5 7v4.5M9.5 7v4.5" />
                  </svg>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}