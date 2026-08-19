import { forwardRef, useImperativeHandle, useRef } from "react";

export interface PlayerHandle {
  seek: (time: number) => void;
  play: () => void;
  pause: () => void;
}

interface Props {
  src: string;
  onTimeUpdate: (time: number) => void;
  onPlay: () => void;
  onPause: () => void;
}

const Player = forwardRef<PlayerHandle, Props>(function Player({ src, onTimeUpdate, onPlay, onPause }, ref) {
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

  return (
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
  );
});

export default Player;