import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./locales/en";
import zhCN from "./locales/zh-CN";
import zhTW from "./locales/zh-TW";

export const LOCALES = ["zh-TW", "zh-CN", "en"] as const;
export type Locale = (typeof LOCALES)[number];

export const LOCALE_KEY = "sfc_locale";
export const DEFAULT_LOCALE: Locale = "zh-TW";

const RESOURCES: Record<Locale, { translation: typeof zhTW }> = {
  "zh-TW": { translation: zhTW },
  "zh-CN": { translation: zhCN },
  en: { translation: en },
};

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

export function detectLocale(): Locale {
  const saved = localStorage.getItem(LOCALE_KEY);
  if (isLocale(saved)) return saved;
  const nav = navigator.language.toLowerCase();
  if (nav.startsWith("zh")) {
    if (nav.includes("hant") || nav.includes("tw") || nav.includes("hk") || nav.includes("mo")) {
      return "zh-TW";
    }
    return "zh-CN";
  }
  if (nav.startsWith("en")) return "en";
  return DEFAULT_LOCALE;
}

export function htmlLang(locale: Locale): string {
  if (locale === "zh-CN") return "zh-Hans-CN";
  if (locale === "zh-TW") return "zh-Hant-TW";
  return "en";
}

export function applyLocale(locale: Locale): void {
  localStorage.setItem(LOCALE_KEY, locale);
  document.documentElement.lang = htmlLang(locale);
  void i18n.changeLanguage(locale);
}

i18n.use(initReactI18next).init({
  resources: RESOURCES,
  lng: detectLocale(),
  fallbackLng: DEFAULT_LOCALE,
  interpolation: { escapeValue: false },
});

document.documentElement.lang = htmlLang(i18n.language as Locale);

export default i18n;