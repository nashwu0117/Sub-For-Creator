import { useEffect, useState } from "react";
import { fetchAuthed, parseError } from "../api/client";

interface AuthedMedia {
  url: string | null;
  error: string | null;
  loading: boolean;
}

/**
 * 以帶 X-Session-Token 的 fetch 下載媒體，回傳 blob URL。
 * <video src> 與 wavesurfer 無法自訂 header，因此先抓成 blob 再餵給播放器；
 * 卸載或換檔時自動 revoke，避免記憶體洩漏。
 */
export function useAuthedMedia(requestUrl: string | null): AuthedMedia {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!requestUrl) return;
    let cancelled = false;
    let objectUrl: string | null = null;
    setLoading(true);
    setError(null);
    fetchAuthed(requestUrl)
      .then(async (res) => {
        if (!res.ok) throw await parseError(res);
        return res.blob();
      })
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "無法載入媒體");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setUrl(null);
    };
  }, [requestUrl]);

  return { url, error, loading };
}
