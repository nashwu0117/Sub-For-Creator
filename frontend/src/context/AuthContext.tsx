import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { getMe, logout as apiLogout } from "../api/client";
import type { User } from "../types";

export type AuthMode = "login" | "register";

export interface ToastState {
  message: string;
  kind: "ok" | "error";
}

interface AuthContextValue {
  user: User | null;
  /** 初始載入 /api/auth/me 中（401 = 未登入，非錯誤） */
  loading: boolean;
  authOpen: boolean;
  authMode: AuthMode;
  openAuth: (mode?: AuthMode) => void;
  closeAuth: () => void;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
  toast: ToastState | null;
  showToast: (message: string, kind?: "ok" | "error") => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [authOpen, setAuthOpen] = useState(false);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [toast, setToast] = useState<ToastState | null>(null);
  const toastTimerRef = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        // 非 401 的暫時性錯誤：維持未登入即可
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    return () => {
      if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    };
  }, []);

  const openAuth = useCallback((mode: AuthMode = "login") => {
    setAuthMode(mode);
    setAuthOpen(true);
  }, []);

  const closeAuth = useCallback(() => setAuthOpen(false), []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // best effort：cookie 清除失敗仍先清掉本地狀態
    } finally {
      setUser(null);
    }
  }, []);

  const showToast = useCallback((message: string, kind: "ok" | "error" = "ok") => {
    setToast({ message, kind });
    if (toastTimerRef.current !== null) window.clearTimeout(toastTimerRef.current);
    toastTimerRef.current = window.setTimeout(() => setToast(null), 3000);
  }, []);

  const value = useMemo(
    () => ({ user, loading, authOpen, authMode, openAuth, closeAuth, setUser, logout, toast, showToast }),
    [user, loading, authOpen, authMode, openAuth, closeAuth, logout, toast, showToast],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}