import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import type { EditorStyle, Segment } from "../types";

interface Props {
  segments: Segment[];
  currentTime: number;
  style: EditorStyle;
  selectedId: number | null;
  onSelect?: (segmentId: number) => void;
  onPositionChange?: (segmentId: number, x: number, y: number) => void;
  onSizeChange?: (segmentId: number, fontSize: number) => void;
}

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

function getDefaultPosition(position: "top" | "bottom"): { x: number; y: number } {
  return position === "top" ? { x: 50, y: 6 } : { x: 50, y: 88 };
}

type ResizeDir = "nw" | "n" | "ne" | "e" | "se" | "s" | "sw" | "w";

const CURSOR_MAP: Record<ResizeDir, string> = {
  nw: "nwse-resize",
  n: "ns-resize",
  ne: "nesw-resize",
  e: "ew-resize",
  se: "nwse-resize",
  s: "ns-resize",
  sw: "nesw-resize",
  w: "ew-resize",
};

const MIN_FONT_SIZE = 16;
const MAX_FONT_SIZE = 200;
const ARROW_STEP = 1;
const ARROW_STEP_FAST = 5;

export default function SubtitlePreview({
  segments,
  currentTime,
  style,
  selectedId,
  onSelect,
  onPositionChange,
  onSizeChange,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const [dragStart, setDragStart] = useState<{
    mouseX: number;
    mouseY: number;
    segX: number;
    segY: number;
  } | null>(null);
  const [resizeStart, setResizeStart] = useState<{
    dir: ResizeDir;
    mouseX: number;
    mouseY: number;
    segX: number;
    segY: number;
    fontSize: number;
  } | null>(null);

  const active = useMemo(() => {
    return segments.find((s) => currentTime >= s.start - 0.05 && currentTime <= s.end + 0.05) ?? null;
  }, [segments, currentTime]);

  const selected = useMemo(() => {
    if (selectedId === null) return null;
    return segments.find((s) => s.id === selectedId) ?? null;
  }, [segments, selectedId]);

  const display = selected ?? active;

  const shadow = useMemo(() => outlineShadow(style), [style]);
  const words = display?.words;
  const activeWords = display && style.karaoke && words && words.length > 0 ? words : null;

  const position = useMemo(() => {
    if (display && display.x !== undefined && display.y !== undefined) {
      return { x: display.x, y: display.y };
    }
    return getDefaultPosition(style.position);
  }, [display, style.position]);

  const handleBoxClick = useCallback(
    (e: React.MouseEvent) => {
      if (!display || !onSelect) return;
      e.stopPropagation();
      onSelect(display.id);
    },
    [display, onSelect],
  );

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!display || !onPositionChange) return;
      e.preventDefault();
      e.stopPropagation();

      setIsDragging(true);
      setDragStart({
        mouseX: e.clientX,
        mouseY: e.clientY,
        segX: position.x,
        segY: position.y,
      });

      if (boxRef.current) {
        boxRef.current.setPointerCapture(e.pointerId);
      }
    },
    [display, onPositionChange, position],
  );

  const handlePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!isDragging || !dragStart || !display || !onPositionChange) return;

      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const dx = ((e.clientX - dragStart.mouseX) / rect.width) * 100;
      const dy = ((e.clientY - dragStart.mouseY) / rect.height) * 100;

      const newX = Math.max(0, Math.min(100, dragStart.segX + dx));
      const newY = Math.max(0, Math.min(100, dragStart.segY + dy));

      onPositionChange(display.id, newX, newY);
    },
    [isDragging, dragStart, display, onPositionChange],
  );

  const handlePointerUp = useCallback(() => {
    setIsDragging(false);
    setDragStart(null);
  }, []);

  const handleResizePointerDown = useCallback(
    (e: React.PointerEvent, dir: ResizeDir) => {
      if (!display || !onPositionChange || !onSizeChange) return;
      e.preventDefault();
      e.stopPropagation();

      setIsResizing(true);
      setResizeStart({
        dir,
        mouseX: e.clientX,
        mouseY: e.clientY,
        segX: position.x,
        segY: position.y,
        fontSize: style.fontSize,
      });

      (e.target as HTMLElement).setPointerCapture(e.pointerId);
    },
    [display, onPositionChange, onSizeChange, position, style.fontSize],
  );

  const handleResizePointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!resizeStart || !display || !onPositionChange || !onSizeChange) return;

      const container = containerRef.current;
      if (!container) return;

      const rect = container.getBoundingClientRect();
      const dx = ((e.clientX - resizeStart.mouseX) / rect.width) * 100;
      const dy = ((e.clientY - resizeStart.mouseY) / rect.height) * 100;
      const { dir } = resizeStart;

      let newX = resizeStart.segX;
      let newY = resizeStart.segY;
      let newFontSize = resizeStart.fontSize;

      if (dir === "e" || dir === "ne" || dir === "se") {
        newFontSize = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, resizeStart.fontSize + dx * 0.8));
      } else if (dir === "w" || dir === "nw" || dir === "sw") {
        newFontSize = Math.max(MIN_FONT_SIZE, Math.min(MAX_FONT_SIZE, resizeStart.fontSize - dx * 0.8));
      }

      if (dir === "n" || dir === "nw" || dir === "ne") {
        newY = Math.max(0, Math.min(100, resizeStart.segY + dy));
      } else if (dir === "s" || dir === "sw" || dir === "se") {
        newY = Math.max(0, Math.min(100, resizeStart.segY + dy));
      }

      if (dir === "nw" || dir === "sw") {
        newX = Math.max(0, Math.min(100, resizeStart.segX + dx));
      } else if (dir === "ne" || dir === "se") {
        newX = Math.max(0, Math.min(100, resizeStart.segX + dx));
      }

      onPositionChange(display.id, newX, newY);
      if (Math.abs(newFontSize - style.fontSize) > 0.5) {
        onSizeChange(display.id, Math.round(newFontSize));
      }
    },
    [resizeStart, display, onPositionChange, onSizeChange, style.fontSize],
  );

  const handleResizePointerUp = useCallback(() => {
    setIsResizing(false);
    setResizeStart(null);
  }, []);

  useEffect(() => {
    if (!display || !onSelect || !onPositionChange) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        return;
      }

      const step = e.shiftKey ? ARROW_STEP_FAST : ARROW_STEP;
      let dx = 0;
      let dy = 0;

      switch (e.key) {
        case "ArrowLeft":
          dx = -step;
          break;
        case "ArrowRight":
          dx = step;
          break;
        case "ArrowUp":
          dy = -step;
          break;
        case "ArrowDown":
          dy = step;
          break;
        default:
          return;
      }

      e.preventDefault();
      const curX = display.x ?? getDefaultPosition(style.position).x;
      const curY = display.y ?? getDefaultPosition(style.position).y;
      const newX = Math.max(0, Math.min(100, curX + dx));
      const newY = Math.max(0, Math.min(100, curY + dy));
      onPositionChange(display.id, newX, newY);
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [display, onSelect, onPositionChange, style.position]);

  const isSelected = display && selectedId === display.id;

  return (
    <div
      ref={containerRef}
      className="subtitle-preview-container"
      aria-hidden="true"
    >
      {display && (
        <div
          ref={boxRef}
          className={[
            "subtitle-preview-box",
            isSelected ? "selected" : "",
            isDragging ? "dragging" : "",
            isResizing ? "resizing" : "",
          ]
            .filter(Boolean)
            .join(" ")}
          style={
            {
              left: `${position.x}%`,
              top: `${position.y}%`,
              transform: "translate(-50%, -50%)",
            } as CSSProperties
          }
          onClick={handleBoxClick}
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={handlePointerUp}
        >
          <div
            className="subtitle-preview-text"
            style={
              {
                "--preview-font-size": `${style.fontSize}px`,
                color: style.fontColor,
                fontWeight: style.bold ? 700 : 400,
                textShadow: shadow,
                pointerEvents: "none",
              } as CSSProperties
            }
          >
            {activeWords
              ? activeWords.map((w, i) => (
                  <span key={i} className={w.start <= currentTime ? "word-done" : "word-pending"}>
                    {w.text}{" "}
                  </span>
                ))
              : display.text}
          </div>

          {isSelected && (
            <div className="subtitle-resize-handles">
              {(["nw", "n", "ne", "e", "se", "s", "sw", "w"] as ResizeDir[]).map((dir) => (
                <div
                  key={dir}
                  className={`resize-handle resize-handle-${dir}`}
                  style={{ cursor: CURSOR_MAP[dir] }}
                  onPointerDown={(e) => handleResizePointerDown(e, dir)}
                  onPointerMove={handleResizePointerMove}
                  onPointerUp={handleResizePointerUp}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
