"use client";

import { useEffect, useRef, useState } from "react";
import { useT } from "@/lib/i18n";

type Detector = { detect: (source: HTMLVideoElement) => Promise<{ rawValue: string }[]> };
type DetectorConstructor = { new (options: { formats: string[] }): Detector };

export default function FabricRollCamera({ onScan, onClose }: { onScan: (code: string) => void; onClose: () => void }) {
  const { t } = useT();
  const video = useRef<HTMLVideoElement>(null);
  const callback = useRef(onScan);
  const [error, setError] = useState(false);
  useEffect(() => { callback.current = onScan; }, [onScan]);
  useEffect(() => {
    let disposed = false;
    let stream: MediaStream | undefined;
    let timer: ReturnType<typeof setTimeout>;
    async function start() {
      try {
        const Constructor = (window as Window & { BarcodeDetector?: DetectorConstructor }).BarcodeDetector;
        if (!Constructor || !navigator.mediaDevices?.getUserMedia) throw new Error("Camera unsupported");
        const detector = new Constructor({ formats: ["qr_code"] });
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
        if (disposed) { stream.getTracks().forEach((track) => track.stop()); return; }
        if (!video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        async function detect() {
          if (disposed || !video.current) return;
          try {
            const codes = await detector.detect(video.current);
            if (disposed) return;
            if (codes[0]?.rawValue) {
              stream?.getTracks().forEach((track) => track.stop());
              callback.current(codes[0].rawValue);
              return;
            }
            timer = setTimeout(detect, 180);
          } catch { if (!disposed) { stream?.getTracks().forEach((track) => track.stop()); setError(true); } }
        }
        timer = setTimeout(detect, 180);
      } catch { stream?.getTracks().forEach((track) => track.stop()); if (!disposed) setError(true); }
    }
    void start();
    return () => { disposed = true; clearTimeout(timer); stream?.getTracks().forEach((track) => track.stop()); };
  }, []);
  return <div className="mt-3">
    {error ? <p role="alert" className="text-sm text-red-700">{t("fabricScans.cameraError")}</p>
      : <video ref={video} muted playsInline className="max-h-72 w-full rounded-md bg-black" aria-label={t("fabricScans.camera")} />}
    <button type="button" className="btn mt-2" onClick={onClose}>{t("fabricScans.closeCamera")}</button>
  </div>;
}
