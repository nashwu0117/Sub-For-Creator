import { useCallback, useEffect, useRef, useState } from "react";

interface PollingState<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  refresh: () => void;
}

/**
 * 輪詢 hook：enabled 時立即執行一次，之後每 intervalMs 執行一次。
 * fetcher 以 ref 保存，避免每次 render 重建 interval。
 */
export function usePolling<T>(fetcher: () => Promise<T>, intervalMs: number, enabled: boolean): PollingState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(false);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const run = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetcherRef.current();
      setData(result);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e : new Error(String(e)));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    void run();
    const id = window.setInterval(() => void run(), intervalMs);
    return () => window.clearInterval(id);
  }, [enabled, intervalMs, run]);

  return { data, error, loading, refresh: run };
}