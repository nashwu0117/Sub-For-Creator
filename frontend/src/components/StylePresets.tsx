import { useTranslation } from "react-i18next";
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
  const { t } = useTranslation();
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
      <h3 className="style-section-title">{t("stylePresets.title")}</h3>
      <div className="inline-row">
        <input
          className="text-input"
          type="text"
          value={name}
          placeholder={t("stylePresets.namePlaceholder")}
          aria-label={t("stylePresets.nameAria")}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSave();
          }}
        />
        <button className="btn btn-sm" onClick={handleSave} disabled={!name.trim()}>
          {justSaved ? t("stylePresets.saved") : t("stylePresets.save")}
        </button>
      </div>

      {presets.length === 0 ? (
        <p className="preset-empty">{t("stylePresets.empty")}</p>
      ) : (
        <ul className="preset-list">
          {presets.map((p) => (
            <li key={p.id} className="preset-item">
              <span className="preset-name">{p.name}</span>
              <span className="preset-actions">
                <button className="btn btn-sm" onClick={() => handleApply(p)}>
                  {t("stylePresets.apply")}
                </button>
                <button className="btn btn-sm btn-danger" onClick={() => handleDelete(p.id)}>
                  {t("stylePresets.delete")}
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
