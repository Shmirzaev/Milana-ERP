"use client";

import { useT } from "@/lib/i18n";

export default function ImagePreviewClient({ title, src }: { title: string; src: string }) {
  const { t } = useT();

  return (
    <main className="min-h-screen bg-[#101010] text-white">
      <div className="flex min-h-screen flex-col">
        <div className="flex h-12 items-center justify-between gap-3 border-b border-white/10 px-4">
          <div className="min-w-0 truncate text-sm font-medium">{title}</div>
          {src ? (
            <a className="text-sm text-white/75 hover:text-white" href={src} download>
              {t("imagePreview.download")}
            </a>
          ) : null}
        </div>
        <div className="flex min-h-0 flex-1 items-center justify-center p-6">
          {src ? (
            <img
              src={src}
              alt={title}
              className="block rounded-md object-contain shadow-sm"
              style={{ maxHeight: "calc(100vh - 96px)", width: "min(1200px, calc(100vw - 48px))" }}
            />
          ) : (
            <div className="rounded-md border border-white/15 px-4 py-3 text-sm text-white/70">
              {t("imagePreview.notFound")}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
