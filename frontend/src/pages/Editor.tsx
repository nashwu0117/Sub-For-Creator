import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getJob, getMediaUrl, getAudioUrl, getSubtitles, putSubtitles } from "../api/client";
import { usePolling } from "../hooks/usePolling";
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
  const { jobId } = useParams<{ jobId: string }>();
  const [job, setJob] = useState<Job | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [segmentsReady, setSegmentsReady] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [style, setStyle] = useState<EditorStyle>(DEFAULT_STYLE);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ message: string; kind: ToastKind } | null>(null);
  const playerRef = useRef<PlayerHandle>(null);
  const waveformRef = useRef<WaveformHandle>(null);
  const toastTimerRef = useRef<number | null>(null);

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

  // 載入作業；done 時直接載入字幕
  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    getJob(jobId)
      .then((j) => {
        if (cancelled) return;
        setJob(j);
        if (j.status === "done") {
          loadSubtitles().catch((e: unknown) => {
            if (!cancelled) setLoadError(e instanceof Error ? e.message : "無法載入字幕資料");
          });
        }
      })
      .catch((e: unknown) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : "無法載入作業");
      });
    return () => {
      cancelled = true;
    };
  }, [jobId, loadSubtitles]);

  // 作業尚未完成 → 每 2 秒輪詢
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
        setLoadError(e instanceof Error ? e.message : "無法載入字幕資料"),
      );
    } else if (polledJob.status === "failed") {
      setLoadError(polledJob.error ?? "處理失敗，請稍後再試");
    }
  }, [polledJob, loadSubtitles]);

  useEffect(() => {
    if (pollError) setLoadError(pollError.message);
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
      // 依順序重新編號 id
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
      showToast("已儲存");
    } catch (e) {
      showToast(e instanceof Error ? e.message : "儲存失敗，請稍後再試", "error");
    } finally {
      setSaving(false);
    }
  }, [jobId, segments, saving, showToast]);

  const activeSegmentId = useMemo(() => {
    const s = segments.find(
      (seg) => currentTime >= seg.start - 0.05 && currentTime <= seg.end + 0.05,
    );
    return s ? s.id : null;
  }, [segments, currentTime]);

  if (!jobId) {
    return (
      <div className="editor-state">
        <div className="editor-state-title">缺少作業編號</div>
        <Link to="/" className="btn btn-primary">
          回到首頁
        </Link>
      </div>
    );
  }

  // 載入失敗 / 作業失敗
  if (loadError || (job && job.status === "failed")) {
    return (
      <div className="editor-state">
        <div className="editor-state-title">無法開啟此作業</div>
        <p className="editor-state-sub">
          {loadError ?? job?.error ?? "作業已過期或不存在（作業保留 48 小時）。"}
        </p>
        <Link to="/" className="btn btn-primary">
          回到首頁
        </Link>
      </div>
    );
  }

  const jobDone = job?.status === "done";

  // 尚未載入完成
  if (!job || !jobDone || !segmentsReady) {
    return (
      <div className="editor-state">
        {job ? (
          <>
            <JobStatusCard job={job} />
            <p className="editor-state-sub">字幕產生完成後將自動載入編輯器…</p>
          </>
        ) : (
          <>
            <span className="spinner spinner-dark" aria-hidden="true" />
            <div className="editor-state-title">載入作業中…</div>
          </>
        )}
      </div>
    );
  }

  const filename = job.meta.filename ?? "未命名";

  return (
    <>
      <div className="editor-header">
        <Link to="/" className="back-link">
          ← 回到首頁
        </Link>
        <h1>{filename}</h1>
        <span className={`status-chip done`}>
          <span className="status-dot" aria-hidden="true" />
          處理完成
        </span>
        {dirty && <span className="dirty-badge">未儲存</span>}
      </div>

      <div className="editor-grid">
        <section className="editor-left">
          <div className="player-wrap">
            <Player
              ref={playerRef}
              src={getMediaUrl(jobId)}
              onTimeUpdate={setCurrentTime}
              onPlay={handleVideoPlay}
              onPause={handleVideoPause}
            />
            <SubtitlePreview segments={segments} currentTime={currentTime} style={style} />
          </div>
          <WaveformTimeline
            ref={waveformRef}
            audioUrl={getAudioUrl(jobId)}
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
          />
          <StylePanel style={style} onChange={setStyle} />
          <ExportPanel jobId={jobId} style={style} onToast={showToast} />
        </aside>
      </div>

      {toast && <div className={`toast${toast.kind === "error" ? " toast-error" : ""}`}>{toast.message}</div>}
    </>
  );
}