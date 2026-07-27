"use client";
import { useEffect } from "react";
import { X } from "lucide-react";
import { useT } from "@/lib/i18n";

export default function Modal({
  open, onClose, title, children, wide = false, full = false,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
  wide?: boolean;
  full?: boolean;
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className={`max-h-[calc(100vh-2rem)] w-full overflow-y-auto rounded-lg bg-[var(--erp-surface)] ${full ? "max-w-[1400px]" : wide ? "max-w-2xl" : "max-w-md"} p-6 shadow-sm`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-[var(--erp-text)]">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-md text-[var(--erp-text-muted)] hover:bg-[var(--erp-subtle)] hover:text-[var(--erp-text)]"
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
