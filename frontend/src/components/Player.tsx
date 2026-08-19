import { forwardRef, useImperativeHandle, useRef } from "react";

export interface PlayerHandle {
  seek: (time: number) => void;
  play: () => void;
  pause: () => void;
}

interface Props {
  /** 已帶 session token 下載完成的 blob URL；null 表示尚未就緒 */
  src: string | null;
  error: string | null;
  onTimeUpdate: (time: number) => void;
  onPlay: () => void;
  onPause: () => void;
}

const Player = forwardRef<PlayerHandle, Props>(function Player(
  { src, error, onTimeUpdate, onPlay, onPause },
  ref,
) {
  const videoRef = useRef<HTMLVideoElement>(null);

  useImperativeHandle(
    ref,
    () => ({
      seek: (time) => {
        const v = videoRef.current;
        if (v && Number.isFinite(time)) v.currentTime = Math.max(0, time);
      },
      play: () => {
        void videoRef.current?.play();
      },
      pause: () => {
        videoRef.current?.pause();
      },
    }),
    [],
  );

  if (error) {
    return (
      <div className="player-overlay" role="alert">
        <div className="player-overlay-title">無法載入影片</div>
        <div className="player-overlay-sub">{error}</div>
      </div>
    );
  }

  return (
    <>
      {src ? (
        <video
          ref={videoRef}
          className="player-video"
          src={src}
          controls
          playsInline
          preload="metadata"
          onTimeUpdate={(e) => onTimeUpdate(e.currentTarget.currentTime)}
          onPlay={onPlay}
          onPause={onPause}
        />
      ) : (
        <div className="player-overlay" aria-live="polite">
          <span className="spinner spinner-dark" aria-hidden="true" />
          <div className="player-overlay-sub">正在載入影片…</div>
        </div>
      )}
    </>
  );
});

export default Player;
