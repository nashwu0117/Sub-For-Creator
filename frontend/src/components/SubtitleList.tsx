import { useTranslation } from "react-i18next";
import { useCallback, useEffect, useRef } from "react";
import type { Segment } from "../types";
import SubtitleItem from "./SubtitleItem";

interface Props {
  segments: Segment[];
  activeId: number | null;
  selectedId: number | null;
  onSeek: (time: number) => void;
  onSelect?: (segmentId: number) => void;
  onChange: (segments: Segment[]) => void;
  onSave: () => void;
  dirty: boolean;
  saving: boolean;
  onAddToDictionary: (text: string) => Promise<void>;
}

export default function SubtitleList({
  segments,
  activeId,
  selectedId,
  onSeek,
  onSelect,
  onChange,
  onSave,
  dirty,
  saving,
  onAddToDictionary,
}: Props) {
  const { t } = useTranslation();
  const itemRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  // 播放中的片段自動捲入視野
  useEffect(() => {
    if (activeId === null) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    itemRefs.current.get(activeId)?.scrollIntoView({
      block: "nearest",
      behavior: reduceMotion ? "auto" : "smooth",
    });
  }, [activeId]);

  const updateSegment = useCallback(
    (id: number, patch: Partial<Segment>) => {
      onChange(segments.map((s) => (s.id === id ? { ...s, ...patch } : s)));
    },
    [segments, onChange],
  );

  const deleteSegment = useCallback(
    (id: number) => {
      onChange(segments.filter((s) => s.id !== id));
    },
    [segments, onChange],
  );

  const addSegment = useCallback(() => {
    const last = segments.length > 0 ? segments[segments.length - 1] : null;
    const nextId = segments.reduce((max, s) => Math.max(max, s.id), -1) + 1;
    const start = last ? last.end : 0;
    onChange([...segments, { id: nextId, start: round1(start), end: round1(start + 2), text: "" }]);
  }, [segments, onChange]);

  return (
    <div className="card subtitle-list-card">
      <div className="subtitle-list-header">
        <h2 className="card-title">{t("subtitleList.title", { count: segments.length })}</h2>
        {dirty && <span className="dirty-badge">{t("common.unsaved")}</span>}
        <button className="btn btn-sm btn-primary" onClick={onSave} disabled={!dirty || saving}>
          {saving ? t("subtitleList.saving") : t("subtitleList.save")}
        </button>
      </div>

      <div className="subtitle-list">
        {segments.map((seg, i) => (
          <div
            key={seg.id}
            ref={(el) => {
              if (el) itemRefs.current.set(seg.id, el);
              else itemRefs.current.delete(seg.id);
            }}
          >
            <SubtitleItem
              segment={seg}
              index={i}
              active={seg.id === activeId}
              selected={seg.id === selectedId}
              onSeek={onSeek}
              onSelect={onSelect}
              onChange={(patch) => updateSegment(seg.id, patch)}
              onDelete={() => deleteSegment(seg.id)}
              onAddToDictionary={onAddToDictionary}
            />
          </div>
        ))}
        {segments.length === 0 && <div className="recent-empty">{t("subtitleList.empty")}</div>}
      </div>

      <button className="btn btn-ghost subtitle-add" onClick={addSegment}>
        {t("subtitleList.add")}
      </button>

      {dirty && (
        <div className="subtitle-list-footer">
          <span className="save-hint">{t("subtitleList.footer")}</span>
        </div>
      )}
    </div>
  );
}

function round1(x: number): number {
  return Math.round(x * 10) / 10;
}