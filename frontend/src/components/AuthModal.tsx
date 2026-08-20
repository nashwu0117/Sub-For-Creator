import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { login, register } from "../api/client";
import { useAuth } from "../context/AuthContext";
import type { User } from "../types";

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const MIN_PASSWORD_LEN = 8;

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export default function AuthModal() {
  const { t } = useTranslation();
  const { authOpen, authMode, closeAuth, setUser, showToast } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const dialogRef = useRef<HTMLDivElement>(null);

  // 每次開啟時重置表單與模式
  useEffect(() => {
    if (authOpen) {
      setMode(authMode);
      setEmail("");
      setPassword("");
      setDisplayName("");
      setError(null);
    }
  }, [authOpen, authMode]);

  // ESC 關閉 + 簡易 focus trap + 開啟時聚焦第一個輸入框
  useEffect(() => {
    if (!authOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        closeAuth();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusables = dialogRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR);
        if (focusables.length === 0) return;
        const first = focusables[0];
        const last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKeyDown);
    const focusTimer = window.setTimeout(() => {
      dialogRef.current?.querySelector<HTMLElement>("input")?.focus();
    }, 0);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.clearTimeout(focusTimer);
    };
  }, [authOpen, closeAuth]);

  // 開啟時鎖定背景捲動
  useEffect(() => {
    if (!authOpen) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prevOverflow;
    };
  }, [authOpen]);

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      if (submitting) return;
      const trimmedEmail = email.trim();
      if (!EMAIL_RE.test(trimmedEmail)) {
        setError(t("auth.invalidEmail"));
        return;
      }
      if (password.length < MIN_PASSWORD_LEN) {
        setError(t("auth.passwordTooShort"));
        return;
      }
      setError(null);
      setSubmitting(true);
      try {
        let user: User;
        if (mode === "register") {
          user = await register(trimmedEmail, password, displayName.trim() || undefined);
        } else {
          user = await login(trimmedEmail, password);
        }
        setUser(user);
        closeAuth();
        showToast(mode === "register" ? t("auth.registerSuccess") : t("auth.loginSuccess"));
      } catch (err) {
        const msg = err instanceof Error ? err.message : "";
        setError(mode === "register" ? t("auth.registerFailed", { msg }) : t("auth.loginFailed", { msg }));
      } finally {
        setSubmitting(false);
      }
    },
    [email, password, displayName, mode, submitting, setUser, closeAuth, showToast, t],
  );

  if (!authOpen) return null;

  const isRegister = mode === "register";

  return (
    <div className="modal-overlay" onClick={closeAuth}>
      <div
        ref={dialogRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={isRegister ? t("auth.registerTitle") : t("auth.loginTitle")}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="modal-close" type="button" onClick={closeAuth} aria-label={t("auth.closeAria")}>
          <svg viewBox="0 0 16 16" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
            <path d="M3 3l10 10M13 3L3 13" />
          </svg>
        </button>
        <h2 className="modal-title">{isRegister ? t("auth.registerTitle") : t("auth.loginTitle")}</h2>
        <form className="auth-form" onSubmit={(e) => void handleSubmit(e)} noValidate>
          {isRegister && (
            <div className="field">
              <label className="field-label" htmlFor="auth-display-name">
                {t("auth.displayName")}
              </label>
              <input
                id="auth-display-name"
                className="text-input"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder={t("auth.displayNamePlaceholder")}
                autoComplete="nickname"
              />
            </div>
          )}
          <div className="field">
            <label className="field-label" htmlFor="auth-email">
              {t("auth.email")}
            </label>
            <input
              id="auth-email"
              className="text-input"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder={t("auth.emailPlaceholder")}
              autoComplete="email"
              required
            />
          </div>
          <div className="field">
            <label className="field-label" htmlFor="auth-password">
              {t("auth.password")}
            </label>
            <input
              id="auth-password"
              className="text-input"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder={t("auth.passwordPlaceholder")}
              autoComplete={isRegister ? "new-password" : "current-password"}
              required
            />
          </div>
          {error && (
            <div className="auth-error" role="alert">
              {error}
            </div>
          )}
          <button className="btn btn-primary auth-submit" type="submit" disabled={submitting}>
            {submitting && <span className="spinner" aria-hidden="true" />}
            {isRegister ? t("auth.submitRegister") : t("auth.submitLogin")}
          </button>
        </form>
        <button
          className="auth-switch"
          type="button"
          onClick={() => setMode(isRegister ? "login" : "register")}
        >
          {isRegister ? t("auth.switchToLogin") : t("auth.switchToRegister")}
        </button>
      </div>
    </div>
  );
}