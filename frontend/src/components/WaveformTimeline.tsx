import { useTranslation } from "react-i18next";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import WaveSurfer from "wavesurfer.js";
import RegionsPlugin, { type Region } from "wavesurfer.js/dist/plugins/regions.js";
import type { Segment } from "../types";

export interface WaveformHandle {
  play: () => void;
  pause: () => void;
  setTime: (time: number) => void;
}

interface Props {
  /** 已帶 session token 下載完成的 blob URL；null 表示尚未就緒 */
  audioUrl: string | null;
  segments: Segment[];
  currentTime: number;
  onTimeChange: (time: number) => void;
  onSeek: (time: number) => void;
  onSegmentsChange: (segments: Segment[]) => void;
}

const REGION_COLOR = "rgba(109, 94, 242, 0.22)";
const REGION_DRAG_COLOR = "rgba(109, 94, 242, 0.40)";
const SYNC_DEBOUNCE_MS = 300;

/**
 * 波形時間軸：以 wavesurfer v7 載入音軌，每個字幕片段為一個可拖曳/縮放的 region。
 * 雙向同步：
 *  - video timeupdate → 本元件（currentTime prop）→ ws.setTime（拖曳中除外）
 *  - region 拖曳（debounce 300ms）→ onSegmentsChange
 *  - region 點擊 / 波形互動 → onSeek
 */
const WaveformTimeline = forwardRef<WaveformHandle, Props>(function WaveformTimeline(
  { audioUrl, segments, currentTime, onTimeChange, onSeek, onSegmentsChange },
  ref,
) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const wsRef = useRef<WaveSurfer | null>(null);
  const regionsPluginRef = useRef<ReturnType<typeof RegionsPlugin.create> | null>(null);
  const regionsRef = useRef<Map<number, Region>>(new Map());
  const segmentsRef = useRef(segments);
  segmentsRef.current = segments;
  const callbacksRef = useRef({ onTimeChange, onSeek, onSegmentsChange });
  callbacksRef.current = { onTimeChange, onSeek, onSegmentsChange };
  const scrubbingRef = useRef(false);
  const debounceRef = useRef<number | null>(null);
  const [ready, setReady] = useState(false);
  const [hidden, setHidden] = useState(false);

  /** 將目前 region 時間寫回 segments（僅在有實際變更時觸發 callback，避免回饋迴圈） */
  const flushSync = useCallback(() => {
    const current = segmentsRef.current;
    let changed = false;
    const next = current.map((seg) => {
      const region = regionsRef.current.get(seg.id);
      if (!region) return seg;
      const start = Math.max(0, region.start);
      const end = Math.max(start + 0.1, region.end);
      if (Math.abs(start - seg.start) > 0.01 || Math.abs(end - seg.end) > 0.01) {
        changed = true;
        return { ...seg, start, end };
      }
      return seg;
    });
    if (changed) callbacksRef.current.onSegmentsChange(next);
  }, []);

  const scheduleSync = useCallback(() => {
    if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
    debounceRef.current = window.setTimeout(() => {
      debounceRef.current = null;
      flushSync();
    }, SYNC_DEBOUNCE_MS);
  }, [flushSync]);

  const addRegionForSegment = useCallback((seg: Segment) => {
    const regions = regionsPluginRef.current;
    if (!regions) return;
    const start = Math.max(0, seg.start);
    const end = Math.max(start + 0.1, seg.end);
    const region = regions.addRegion({
      id: String(seg.id),
      start,
      end,
      drag: true,
      resize: true,
      color: REGION_COLOR,
      content: seg.text.length > 12 ? seg.text.slice(0, 12) + "…" : seg.text,
    });
    regionsRef.current.set(seg.id, region);
  }, []);

  // 建立 wavesurfer 實例（僅依 audioUrl 重建）
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !audioUrl) return;
    let cancelled = false;
    let ws: WaveSurfer | null = null;

    ws = WaveSurfer.create({
      container,
      url: audioUrl,
      height: 96,
      waveColor: "#3a4152",
      progressColor: "#6d5ef2",
      cursorColor: "#38bdf8",
      cursorWidth: 2,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      hideScrollbar: true,
    });
    wsRef.current = ws;
    // 靜音：播放同步只走波形指針，聲音由 <video> 負責，避免雙重音訊
    ws.setMuted(true);

    const regions = ws.registerPlugin(RegionsPlugin.create());
    regionsPluginRef.current = regions;

    ws.on("ready", () => {
      if (cancelled) return;
      setReady(true);
      for (const seg of segmentsRef.current) addRegionForSegment(seg);
    });

    ws.on("timeupdate", (t) => {
      if (ws?.isPlaying()) callbacksRef.current.onTimeChange(t);
    });

    // 使用者點擊波形任意處 → 影片跳轉
    ws.on("interaction", () => {
      if (ws && !scrubbingRef.current) callbacksRef.current.onSeek(ws.getCurrentTime());
    });

    ws.on("error", () => {
      if (cancelled) return;
      setHidden(true);
    });

    regions.on("region-update", (region: Region) => {
      scrubbingRef.current = true;
      region.setOptions({ color: REGION_DRAG_COLOR });
      scheduleSync();
    });
    regions.on("region-updated", (region: Region) => {
      scrubbingRef.current = false;
      region.setOptions({ color: REGION_COLOR });
      flushSync();
    });
    regions.on("region-clicked", (region) => {
      callbacksRef.current.onSeek(region.start);
    });

    return () => {
      cancelled = true;
      if (debounceRef.current !== null) window.clearTimeout(debounceRef.current);
      debounceRef.current = null;
      regionsRef.current.clear();
      regionsPluginRef.current = null;
      ws?.destroy();
      wsRef.current = null;
    };
  }, [audioUrl, addRegionForSegment, flushSync, scheduleSync]);

  // segments 變更 → 同步 regions（新增 / 更新 / 移除）
  useEffect(() => {
    if (!ready || scrubbingRef.current) return;
    const seen = new Set<number>();
    for (const seg of segments) {
      seen.add(seg.id);
      const existing = regionsRef.current.get(seg.id);
      if (existing) {
        const start = Math.max(0, seg.start);
        const end = Math.max(start + 0.1, seg.end);
        if (Math.abs(existing.start - start) > 0.01 || Math.abs(existing.end - end) > 0.01) {
          existing.setOptions({ start, end });
        }
      } else {
        addRegionForSegment(seg);
      }
    }
    for (const [id, region] of regionsRef.current) {
      if (!seen.has(id)) {
        region.remove();
        regionsRef.current.delete(id);
      }
    }
  }, [segments, ready, addRegionForSegment]);

  // video 時間 → wavesurfer 指針（拖曳中不覆蓋）
  useEffect(() => {
    const ws = wsRef.current;
    if (!ws || !ready || scrubbingRef.current) return;
    const t = ws.getCurrentTime();
    if (Math.abs(t - currentTime) > 0.1) {
      ws.setTime(currentTime);
    }
  }, [currentTime, ready]);

  useImperativeHandle(
    ref,
    () => ({
      play: () => {
        const ws = wsRef.current;
        if (ws && ready) void ws.play();
      },
      pause: () => {
        const ws = wsRef.current;
        if (ws) ws.pause();
      },
      setTime: (time) => {
        const ws = wsRef.current;
        if (ws && ready && !scrubbingRef.current) ws.setTime(time);
      },
    }),
    [ready],
  );

  if (hidden) {
    return (
      <div className="waveform-card">
        <div className="card-title">{t("waveform.title")}</div>
        <div className="waveform-empty">{t("waveform.hidden")}</div>
      </div>
    );
  }

  return (
    <div className="waveform-card">
      <div className="card-title">{t("waveform.hint")}</div>
      {audioUrl ? (
        <div className="waveform-container" ref={containerRef} />
      ) : (
        <div className="waveform-empty">{t("waveform.loading")}</div>
      )}
    </div>
  );
});

export default WaveformTimeline;