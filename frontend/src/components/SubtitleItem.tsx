import { useEffect, useRef } from "react";
import type { Segment } from "../types";

interface Props {
  segment: Segment;
  index: number;
  active: boolean;
  onSeek: (time: number) => void;
  onChange: (patch: Partial<Segment>) => void;
  onDelete: () => void;
}

function formatTime(t: number): string {
  const safe = Math.max(0, t);
  const m = Math.floor(safe / 60);
  const s = safe - m * 60;
  return `${String(m).padStart(2, "0")}:${s.toFixed(2).padStart(5, "0")}`;
}

function parseTime(str: string): number | null {
  const m = /^(\d+):(\d{1,2}(?:\.\d{1,3})?)$/.exec(str.trim());
  if (!m) return null;
  const minutes = parseInt(m[1], 10);
  const seconds = parseFloat(m[2]);
  if (!Number.isFinite(seconds) || seconds >= 60) return null;
  return minutes * 60 + seconds;
}

function round2(x: number): number {
  return Math.round(x * 100) / 100;
}

export default function SubtitleItem({ segment, index, active, onSeek, onChange, onDelete }: Props) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自動調整高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [segment.text]);

  return (
    <div
      className={`subtitle-item${active ? " active" : ""}`}
      onClick={() => onSeek(segment.start)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => {
        if (e.key === "Enter" && (e.target as HTMLElement).tagName !== "TEXTAREA") {
          onSeek(segment.start);
        }
      }}
    >
      <div className="subtitle-item-top">
        <span className="subtitle-index">{String(index + 1).padStart(2, "0")}</span>
        <div className="subtitle-time-inputs" onClick={(e) => e.stopPropagation()}>
          <input
            className="time-input"
            key={`start-${segment.start}`}
            defaultValue={formatTime(segment.start)}
            aria-label={`片段 ${index + 1} 開始時間`}
            inputMode="decimal"
            onBlur={(e) => {
              const t = parseTime(e.target.value);
              if (t !== null && Math.abs(t - segment.start) > 0.001) {
                onChange({ start: round2(t) });
              } else if (t === null) {
                e.target.value = formatTime(segment.start);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
          />
          <span className="time-sep">→</span>
          <input
            className="time-input"
            key={`end-${segment.end}`}
            defaultValue={formatTime(segment.end)}
            aria-label={`片段 ${index + 1} 結束時間`}
            inputMode="decimal"
            onBlur={(e) => {
              const t = parseTime(e.target.value);
              if (t !== null && Math.abs(t - segment.end) > 0.001) {
                onChange({ end: round2(Math.max(t, segment.start + 0.1)) });
              } else if (t === null) {
                e.target.value = formatTime(segment.end);
              }
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
            }}
          />
          <button
            type="button"
            className="nudge-btn"
            title="開始時間 -0.1 秒"
            aria-label={`片段 ${index + 1} 開始時間減 0.1 秒`}
            onClick={() => onChange({ start: round2(Math.max(0, segment.start - 0.1)) })}
          >
            −
          </button>
          <button
            type="button"
            className="nudge-btn"
            title="開始時間 +0.1 秒"
            aria-label={`片段 ${index + 1} 開始時間加 0.1 秒`}
            onClick={() => onChange({ start: round2(segment.start + 0.1) })}
          >
            +
          </button>
        </div>
        <button
          type="button"
          className="subtitle-delete"
          title="刪除此字幕"
          aria-label={`刪除片段 ${index + 1}`}
          onClick={(e) => {
            e.stopPropagation();
            onDelete();
          }}
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M3 6h18" />
            <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
            <path d="M10 11v6" />
            <path d="M14 11v6" />
          </svg>
        </button>
      </div>
      <textarea
        ref={textareaRef}
        className="subtitle-textarea"
        value={segment.text}
        rows={1}
        placeholder="輸入字幕文字…"
        aria-label={`片段 ${index + 1} 文字`}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onChange({ text: e.target.value })}
      />
    </div>
  );
}