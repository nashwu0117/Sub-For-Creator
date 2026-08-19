import { useState } from "react";
import type { EditorStyle, StylePreset } from "../types";

interface Props {
  style: EditorStyle;
  onApply: (style: EditorStyle) => void;
}

const PRESETS_KEY = "sfc_style_presets";
const MAX_PRESETS = 10;

function loadPresets(): StylePreset[] {
  try {
    const raw = localStorage.getItem(PRESETS_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as StylePreset[]) : [];
  } catch {
    return [];
  }
}

function persistPresets(presets: StylePreset[]): void {
  localStorage.setItem(PRESETS_KEY, JSON.stringify(presets));
}

function generateId(): string {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

export default function StylePresets({ style, onApply }: Props) {
  const [presets, setPresets] = useState<StylePreset[]>(loadPresets);
  const [name, setName] = useState("");
  const [justSaved, setJustSaved] = useState(false);

  const handleSave = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    const next = [...presets, { id: generateId(), name: trimmed, style: { ...style } }];
    if (next.length > MAX_PRESETS) next.splice(0, next.length - MAX_PRESETS);
    setPresets(next);
    persistPresets(next);
    setName("");
    setJustSaved(true);
    window.setTimeout(() => setJustSaved(false), 1500);
  };

  const handleApply = (preset: StylePreset) => {
    onApply({ ...preset.style });
  };

  const handleDelete = (id: string) => {
    const next = presets.filter((p) => p.id !== id);
    setPresets(next);
    persistPresets(next);
  };

  return (
    <div className="style-section">
      <h3 className="style-section-title">樣式預設</h3>
      <div className="inline-row">
        <input
          className="text-input"
          type="text"
          value={name}
          placeholder="預設名稱（如：白色大字）"
          aria-label="預設名稱"
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
        />
        <button className="btn btn-sm" onClick={handleSave} disabled={!name.trim()}>
          {justSaved ? "已儲存" : "儲存預設"}
        </button>
      </div>

      {presets.length === 0 ? (
        <p className="preset-empty">尚未儲存任何樣式預設。</p>
      ) : (
        <ul className="preset-list">
          {presets.map((p) => (
            <li key={p.id} className="preset-item">
              <span className="preset-name">{p.name}</span>
              <span className="preset-actions">
                <button className="btn btn-sm" onClick={() => handleApply(p)}>
                  套用
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(p.id)}>
                  刪除
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
