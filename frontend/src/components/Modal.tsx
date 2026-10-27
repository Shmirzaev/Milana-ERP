"use client";
import { useEffect } from "react";
import { X } from "lucide-react";
import { useT } from "@/lib/i18n";

export default function Modal({
  open, onClose, title, children, wide = false, full = false, closeOnOutsideClick = true,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
  full?: boolean;
  closeOnOutsideClick?: boolean;
}) {
  const { t } = useT();

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-2 sm:p-4"
      onClick={closeOnOutsideClick ? onClose : undefined}
    >
      <div
        className={`max-h-[calc(100dvh-1rem)] w-full min-w-0 overflow-y-auto overscroll-contain rounded-lg bg-[var(--erp-surface)] ${full ? "max-w-[1400px]" : wide ? "max-w-2xl" : "max-w-md"} p-4 shadow-sm sm:max-h-[calc(100dvh-2rem)] sm:p-6`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex min-w-0 items-start justify-between gap-3">
          <h2 className="min-w-0 break-words text-lg font-semibold leading-tight text-[var(--erp-text)]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-[var(--erp-text-muted)] hover:bg-[var(--erp-subtle)] hover:text-[var(--erp-text)]"
            aria-label={t("common.close")}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
