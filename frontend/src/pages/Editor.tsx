import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { addDictionaryTerms, createWork, getJob, getMediaUrl, getAudioUrl, getSubtitles, putSubtitles } from "../api/client";
import { useAuth } from "../context/AuthContext";
import { usePolling } from "../hooks/usePolling";
import { useAuthedMedia } from "../hooks/useAuthedMedia";
import type { EditorStyle, Job, Segment } from "../types";
import Player, { type PlayerHandle } from "../components/Player";
import SubtitlePreview from "../components/SubtitlePreview";
import WaveformTimeline, { type WaveformHandle } from "../components/WaveformTimeline";
import SubtitleList from "../components/SubtitleList";
import StylePanel from "../components/StylePanel";
import ExportPanel from "../components/ExportPanel";
import JobStatusCard from "../components/JobStatusCard";

const DEFAULT_STYLE: EditorStyle = {
  fontSize: 64,
  fontColor: "#FFFFFF",
  outlineColor: "#000000",
  bold: false,
  position: "bottom",
  karaoke: false,
  fade: false,
};

type ToastKind = "ok" | "error";

export default function Editor() {
  const { t } = useTranslation();
  const { jobId } = useParams<{ jobId: string }>();
  const { user, openAuth } = useAuth();
  const [job, setJob] = useState<Job | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [segmentsReady, setSegmentsReady] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [style, setStyle] = useState<EditorStyle>(DEFAULT_STYLE);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; kind: ToastKind } | null>(null);
  /** transient polling errors (e.g. network hiccup); do not break the editor */
  const [pollNote, setPollNote] = useState<string | null>(null);
  const [workSaved, setWorkSaved] = useState(false);
  const [savingWork, setSavingWork] = useState(false);
  const playerRef = useRef<PlayerHandle>(null);
  const waveformRef = useRef<WaveformHandle>(null);
  const toastTimerRef = useRef<number | null>(null);

  // download media with the session token only once the job is done (<video>/wavesurfer can't set headers)
  const media = useAuthedMedia(job && job.status === "done" && jobId ? getMediaUrl(jobId) : null);
  const audio = useAuthedMedia(job && job.status === "done" && jobId ? getAudioUrl(jobId) : null);

  const showToast = useCallback((message: string, kind: ToastKind = "ok") => {
    setToast({ message, kind });
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 3000);
  }, []);

  const loadSubtitles = useCallback(async () => {
    if (!jobId) return;
    const subs = await getSubtitles(jobId);
    setSegments(subs.segments);
    setSegmentsReady(true);
  }, [jobId]);

  // load the job; load subtitles immediately when done
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    getJob(jobId)
      .then((j) => {
        if (cancelled) return;
        setJob(j);
        if (j.status === "done") {
          loadSubtitles().catch((e: unknown) => {
            if (!cancelled) setLoadError(e instanceof Error ? e.message : t("editor.loadSubtitlesFail"));
          });
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : t("editor.loadJobFail"));
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, loadSubtitles, t]);

  // job not finished yet → poll every 2s
  const needsPolling =
    job !== null && (job.status === "queued" || job.status === "processing") && !segmentsReady;
  const { data: polledJob, error: pollError } = usePolling(
    () => getJob(jobId ?? ""),
    2000,
    needsPolling && jobId !== undefined,
  );

  useEffect(() => {
    if (!polledJob) return;
    setJob(polledJob);
    if (polledJob.status === "done") {
      loadSubtitles().catch((e: unknown) =>
        setLoadError(e instanceof Error ? e.message : t("editor.loadSubtitlesFail")),
      );
    } else if (polledJob.status === "failed") {
      setLoadError(polledJob.error ?? t("editor.processFailed"));
    }
  }, [polledJob, loadSubtitles, t]);

  // polling failure is only a hint (the job may still be running); cleared on next success
  useEffect(() => {
    setPollNote(pollError ? pollError.message : null);
  }, [pollError]);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  const handleSegmentsChange = useCallback((next: Segment[]) => {
    setSegments(next);
    setDirty(true);
  }, []);

  const handleSeek = useCallback((time: number) => {
    setCurrentTime(time);
    playerRef.current?.seek(time);
  }, []);

  const handleVideoPlay = useCallback(() => {
    waveformRef.current?.play();
  }, []);

  const handleVideoPause = useCallback(() => {
    waveformRef.current?.pause();
  }, []);

  const handleSave = useCallback(async () => {
    if (!jobId || saving) return;
    setSaving(true);
    try {
      // renumber ids in order
      const clean = segments.map((s, i) => ({
        id: i,
        start: s.start,
        end: s.end,
        text: s.text,
        ...(s.words && s.words.length > 0 ? { words: s.words } : {}),
      }));
      await putSubtitles(jobId, clean);
      setSegments(clean);
      setDirty(false);
      showToast(t("editor.saved"));
    } catch (e) {
      showToast(e instanceof Error ? e.message : t("editor.saveFailed"), "error");
    } finally {
      setSaving(false);
    }
  }, [jobId, segments, saving, showToast, t]);

  const handleSaveWork = useCallback(async () => {
    if (!jobId || savingWork) return;
    if (!user) {
      openAuth("login");
      return;
    }
    setSavingWork(true);
    try {
      await createWork(jobId);
      setWorkSaved(true);
      showToast(t("works.savedToast"));
    } catch (e) {
      showToast(e instanceof Error ? e.message : t("works.saveFailed", { msg: "" }), "error");
    } finally {
      setSavingWork(false);
    }
  }, [jobId, user, savingWork, openAuth, showToast, t]);

  const handleAddToDictionary = useCallback(async (text: string) => {
    await addDictionaryTerms([text]);
  }, []);

  const activeSegmentId = useMemo(() => {
    const s = segments.find(
      (seg) => currentTime >= seg.start - 0.05 && currentTime <= seg.end + 0.05,
    );
    return s ? s.id : null;
  }, [segments, currentTime]);

  if (!jobId) {
    return (
      <div className="editor-state">
        <div className="editor-state-title">{t("editor.missingJob")}</div>
        <Link to="/" className="btn btn-primary">
          {t("common.backHome")}
        </Link>
      </div>
    );
  }

  // load failure / job failure
  if (loadError || (job && job.status === "failed")) {
    return (
      <div className="editor-state">
        <div className="editor-state-title">{t("editor.cannotOpen")}</div>
        <p className="editor-state-sub">
          {loadError ?? job?.error ?? t("editor.expired")}
        </p>
        <Link to="/" className="btn btn-primary">
          {t("common.backHome")}
        </Link>
      </div>
    );
  }

  const jobDone = job?.status === "done";

  // not fully loaded yet
  if (!job || !jobDone || !segmentsReady) {
    return (
      <div className="editor-state">
        {job ? (
          <>
            <JobStatusCard job={job} />
            {pollNote && (
              <div className="error-box" role="alert">
                <span>{t("editor.pollNote", { msg: pollNote })}</span>
              </div>
            )}
            <p className="editor-state-sub">{t("editor.loadingSubs")}</p>
          </>
        ) : (
          <>
            <span className="spinner spinner-dark" aria-hidden="true" />
            <div className="editor-state-title">{t("editor.loadingJob")}</div>
          </>
        )}
      </div>
    );
  }

  const filename = job.meta.filename ?? t("editor.unnamed");

  return (
    <>
      <div className="editor-header">
        <Link to="/" className="back-link">
          {t("editor.backLink")}
        </Link>
        <h1>{filename}</h1>
        <span className={`status-chip done`}>
          <span className="status-dot" aria-hidden="true" />
          {t("editor.done")}
        </span>
        {dirty && <span className="dirty-badge">{t("common.unsaved")}</span>}
        <span className="header-spacer" />
        <button
          className={`btn btn-sm${workSaved ? " btn-saved" : " btn-primary"}`}
          type="button"
          onClick={() => void handleSaveWork()}
          disabled={workSaved || savingWork}
          aria-label={workSaved ? t("works.saved") : t("works.save")}
        >
          {savingWork && <span className="spinner" aria-hidden="true" />}
          {workSaved ? t("works.saved") : t("works.save")}
        </button>
      </div>

      <div className="editor-grid">
        <section className="editor-left">
          <div className="player-wrap">
            <Player
              ref={playerRef}
              src={media.url}
              error={media.error}
              onTimeUpdate={setCurrentTime}
              onPlay={handleVideoPlay}
              onPause={handleVideoPause}
            />
            <SubtitlePreview segments={segments} currentTime={currentTime} style={style} />
          </div>
          <WaveformTimeline
            ref={waveformRef}
            audioUrl={audio.url}
            segments={segments}
            currentTime={currentTime}
            onTimeChange={setCurrentTime}
            onSeek={handleSeek}
            onSegmentsChange={handleSegmentsChange}
          />
        </section>

        <aside className="editor-right">
          <SubtitleList
            segments={segments}
            activeId={activeSegmentId}
            onSeek={handleSeek}
            onChange={handleSegmentsChange}
            onSave={() => void handleSave()}
            dirty={dirty}
            saving={saving}
            onAddToDictionary={handleAddToDictionary}
          />
          <StylePanel style={style} onChange={setStyle} />
          <ExportPanel jobId={jobId} style={style} onToast={showToast} />
        </aside>
      </div>

      {toast && (
        <div
          className={`toast${toast.kind === "error" ? " toast-error" : ""}`}
          role={toast.kind === "error" ? "alert" : "status"}
          aria-live={toast.kind === "error" ? "assertive" : "polite"}
          aria-atomic="true"
        >
          {toast.message}
        </div>
      )}
    </>
  );
}