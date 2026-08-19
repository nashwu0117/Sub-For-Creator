import { useTranslation } from "react-i18next";
import type { EditorStyle } from "../types";
import FontSettings from "./FontSettings";
import StylePresets from "./StylePresets";

interface Props {
  style: EditorStyle;
  onChange: (style: EditorStyle) => void;
}

export default function StylePanel({ style, onChange }: Props) {
  const { t } = useTranslation();
  return (
    <div className="card">
      <h2 className="card-title">{t("stylePanel.title")}</h2>
      <div className="style-panel">
        <div className="field">
          <div className="range-row">
            <span className="field-label" style={{ flex: "0 0 auto" }}>
              {t("stylePanel.fontSize")}
            </span>
            <input
              className="range-input"
              type="range"
              min={32}
              max={120}
              step={2}
              value={style.fontSize}
              aria-label={t("stylePanel.fontSize")}
              onChange={(e) => onChange({ ...style, fontSize: Number(e.target.value) })}
            />
            <span className="range-value">{style.fontSize} px</span>
          </div>
        </div>

        <div className="style-row">
          <span className="field-label">{t("stylePanel.fontColor")}</span>
          <span className="color-input-wrap">
            <input
              className="color-input"
              type="color"
              value={style.fontColor}
              aria-label={t("stylePanel.fontColor")}
              onChange={(e) => onChange({ ...style, fontColor: e.target.value })}
            />
            <span className="color-hex">{style.fontColor.toUpperCase()}</span>
          </span>
        </div>

        <div className="style-row">
          <span className="field-label">{t("stylePanel.outlineColor")}</span>
          <span className="color-input-wrap">
            <input
              className="color-input"
              type="color"
              value={style.outlineColor}
              aria-label={t("stylePanel.outlineColor")}
              onChange={(e) => onChange({ ...style, outlineColor: e.target.value })}
            />
            <span className="color-hex">{style.outlineColor.toUpperCase()}</span>
          </span>
        </div>

        <div className="style-row">
          <label className="switch">
            <input
              type="checkbox"
              checked={style.bold}
              onChange={(e) => onChange({ ...style, bold: e.target.checked })}
            />
            <span className="switch-track" aria-hidden="true" />
            <span className="switch-label">{t("stylePanel.bold")}</span>
          </label>
        </div>

        <div className="style-row">
          <div className="switch-row">
            <label className="switch">
              <input
                type="checkbox"
                checked={style.fade}
                onChange={(e) => onChange({ ...style, fade: e.target.checked })}
              />
              <span className="switch-track" aria-hidden="true" />
              <span className="switch-label">{t("stylePanel.fade")}</span>
            </label>

            <label className="switch">
              <input
                type="checkbox"
                checked={style.karaoke}
                onChange={(e) => onChange({ ...style, karaoke: e.target.checked })}
              />
              <span className="switch-track" aria-hidden="true" />
              <span className="switch-label">{t("stylePanel.karaoke")}</span>
            </label>
          </div>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="subtitle-position">
            {t("stylePanel.position")}
          </label>
          <select
            id="subtitle-position"
            className="select-input"
            value={style.position}
            onChange={(e) => onChange({ ...style, position: e.target.value as EditorStyle["position"] })}
          >
            <option value="bottom">{t("stylePanel.bottom")}</option>
            <option value="top">{t("stylePanel.top")}</option>
          </select>
        </div>

        <FontSettings style={style} onChange={onChange} />
        <StylePresets style={style} onApply={onChange} />
      </div>
    </div>
  );
}