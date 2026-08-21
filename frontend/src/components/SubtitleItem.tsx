import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Segment } from "../types";

interface Props {
  segment: Segment;
  index: number;
  active: boolean;
  selected?: boolean;
  onSeek: (time: number) => void;
  onSelect?: (segmentId: number) => void;
  onChange: (patch: Partial<Segment>) => void;
  onDelete: () => void;
  onAddToDictionary: (text: string) => Promise<void>;
}

type DictState = "idle" | "adding" | "added" | "error";

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

export default function SubtitleItem({
  segment,
  index,
  active,
  selected,
  onSeek,
  onSelect,
  onChange,
  onDelete,
  onAddToDictionary,
}: Props) {
  const { t } = useTranslation();
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const dictTimerRef = useRef<number | null>(null);
  const [dictState, setDictState] = useState<DictState>("idle");

  // 自動調整高度
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [segment.text]);

  useEffect(() => {
    return () => {
      if (dictTimerRef.current !== null) window.clearTimeout(dictTimerRef.current);
    };
  }, []);

  const handleAddToDictionary = useCallback(async () => {
    if (dictState === "adding") return;
    const text = segment.text.trim();
    if (!text) return;
    setDictState("adding");
    try {
      await onAddToDictionary(text);
      setDictState("added");
    } catch {
      setDictState("error");
    }
    if (dictTimerRef.current !== null) window.clearTimeout(dictTimerRef.current);
    dictTimerRef.current = window.setTimeout(() => setDictState("idle"), 1500);
  }, [dictState, segment.text, onAddToDictionary]);

  return (
    <div
      className={`subtitle-item${active ? " active" : ""}${selected ? " selected" : ""}`}
      onClick={() => {
        onSeek(segment.start);
        onSelect?.(segment.id);
      }}
      aria-current={active ? "true" : undefined}
    >
      <div className="subtitle-item-top">
        <button
          type="button"
          className="subtitle-index subtitle-seek"
          onClick={(e) => {
            e.stopPropagation();
            onSeek(segment.start);
          }}
          aria-label={t("subtitleItem.jumpTo", { n: index + 1 })}
        >
          {String(index + 1).padStart(2, "0")}
        </button>
        <div className="subtitle-time-inputs" onClick={(e) => e.stopPropagation()}>
          <input
            className="time-input"
            key={`start-${segment.start}`}
            defaultValue={formatTime(segment.start)}
            aria-label={t("subtitleItem.startTime", { n: index + 1 })}
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
            aria-label={t("subtitleItem.endTime", { n: index + 1 })}
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
            title={t("subtitleItem.startMinusTitle")}
            aria-label={t("subtitleItem.startMinusAria", { n: index + 1 })}
            onClick={() => onChange({ start: round2(Math.max(0, segment.start - 0.1)) })}
          >
            −
          </button>
          <button
            type="button"
            className="nudge-btn"
            title={t("subtitleItem.startPlusTitle")}
            aria-label={t("subtitleItem.startPlusAria", { n: index + 1 })}
            onClick={() => onChange({ start: round2(segment.start + 0.1) })}
          >
            +
          </button>
        </div>
        <span className="dict-wrap">
          <button
            type="button"
            className={`dict-btn${dictState === "added" ? " added" : ""}${dictState === "error" ? " error" : ""}`}
            title={t("subtitleItem.addToDictionary")}
            aria-label={t("subtitleItem.addToDictionary")}
            disabled={dictState === "adding"}
            onClick={(e) => {
              e.stopPropagation();
              void handleAddToDictionary();
            }}
          >
            {dictState === "added" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M20 6 9 17l-5-5" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
                <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
              </svg>
            )}
          </button>
          {dictState === "added" && (
            <span className="dict-feedback added" role="status">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M20 6 9 17l-5-5" />
              </svg>
              {t("subtitleItem.addedToDictionary")}
            </span>
          )}
          {dictState === "error" && (
            <span className="dict-feedback error" role="alert">
              {t("subtitleItem.addFailed")}
            </span>
          )}
        </span>
        <button
          type="button"
          className="subtitle-delete"
          title={t("subtitleItem.deleteTitle")}
          aria-label={t("subtitleItem.deleteAria", { n: index + 1 })}
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
        placeholder={t("subtitleItem.placeholder")}
        aria-label={t("subtitleItem.textAria", { n: index + 1 })}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onChange({ text: e.target.value })}
      />
      {(segment.x !== undefined || segment.y !== undefined) && (
        <div className="subtitle-position-info">
          <span className="position-label">
            Position: {Math.round(segment.x ?? 50)}%, {Math.round(segment.y ?? 88)}%
          </span>
          <button
            type="button"
            className="nudge-btn"
            title="Reset position"
            aria-label="Reset position"
            onClick={(e) => {
              e.stopPropagation();
              onChange({ x: undefined, y: undefined });
            }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
            </svg>
          </button>
        </div>
      )}
    </div>
  );
}