import { useMemo } from "react";
import type { EditorStyle, Segment } from "../types";

interface Props {
  segments: Segment[];
  currentTime: number;
  style: EditorStyle;
}

/** 以多方向 text-shadow 產生外框效果 */
function outlineShadow(style: EditorStyle): string {
  const px = Math.max(1, Math.round(style.fontSize / 32));
  const c = style.outlineColor;
  return [
    `${px}px ${px}px 0 ${c}`,
    `-${px}px ${px}px 0 ${c}`,
    `${px}px -${px}px 0 ${c}`,
    `-${px}px -${px}px 0 ${c}`,
    `${px}px 0 0 ${c}`,
    `-${px}px 0 0 ${c}`,
    `0 ${px}px 0 ${c}`,
    `0 -${px}px 0 ${c}`,
  ].join(", ");
}

/**
 * 影片上的字幕預覽疊層。
 * 卡拉 OK 模式：已播過的單字以強調色顯示（依 word.start <= currentTime 判斷）。
 */
export default function SubtitlePreview({ segments, currentTime, style }: Props) {
  const active = useMemo(() => {
    return segments.find((s) => currentTime >= s.start - 0.05 && currentTime <= s.end + 0.05) ?? null;
  }, [segments, currentTime]);

  const shadow = useMemo(() => outlineShadow(style), [style]);
  const words = active?.words;
  const activeWords = active && style.karaoke && words && words.length > 0 ? words : null;

  return (
    <div className={`subtitle-preview ${style.position === "top" ? "is-top" : "is-bottom"}`} aria-hidden="true">
      {active && (
        <div
          className="subtitle-preview-text"
          style={{
            fontSize: style.fontSize,
            color: style.fontColor,
            fontWeight: style.bold ? 700 : 400,
            textShadow: shadow,
          }}
        >
          {activeWords
            ? activeWords.map((w, i) => (
                <span key={i} className={w.start <= currentTime ? "word-done" : "word-pending"}>
                  {w.text}{" "}
                </span>
              ))
            : active.text}
        </div>
      )}
    </div>
  );
}