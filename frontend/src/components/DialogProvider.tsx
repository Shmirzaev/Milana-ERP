"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { AlertTriangle, Info } from "lucide-react";
import Modal from "@/components/Modal";
import { useT } from "@/lib/i18n";

type DialogOptions = {
  title?: string;
  message: React.ReactNode;
  confirmText?: string;
  cancelText?: string;
  tone?: "default" | "danger";
};

type DialogState = DialogOptions & {
  kind: "alert" | "confirm";
  resolve: (value: boolean) => void;
};

type DialogApi = {
  notify: (options: string | DialogOptions) => Promise<void>;
  ask: (options: string | DialogOptions) => Promise<boolean>;
};

const DialogContext = createContext<DialogApi | null>(null);

function normalizeOptions(options: string | DialogOptions): DialogOptions {
  return typeof options === "string" ? { message: options } : options;
}

export function DialogProvider({ children }: { children: React.ReactNode }) {
  const { t } = useT();
  const [dialog, setDialog] = useState<DialogState | null>(null);

  const open = useCallback((kind: DialogState["kind"], options: string | DialogOptions) => {
    return new Promise<boolean>((resolve) => {
      setDialog({ kind, ...normalizeOptions(options), resolve });
    });
  }, []);

  const close = useCallback((value: boolean) => {
    setDialog((current) => {
      current?.resolve(value);
      return null;
    });
  }, []);

  const api = useMemo<DialogApi>(() => ({
    notify: async (options) => {
      await open("alert", options);
    },
    ask: (options) => open("confirm", options),
  }), [open]);

  const isDanger = dialog?.tone === "danger";
  const title = dialog?.title ?? (dialog?.kind === "confirm" ? t("common.confirm") : t("common.notice"));

  return (
    <DialogContext.Provider value={api}>
      {children}
      <Modal open={!!dialog} onClose={() => close(false)} title={title}>
        {dialog && (
          <div className="space-y-4">
            <div className="flex items-start gap-3">
              <div className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md ${isDanger ? "bg-red-50 text-red-700" : "bg-[var(--erp-subtle)] text-[var(--erp-text)]"}`}>
                {isDanger ? <AlertTriangle aria-hidden="true" /> : <Info aria-hidden="true" />}
              </div>
              <div className="min-w-0 text-sm leading-6 text-[var(--erp-text)]">{dialog.message}</div>
            </div>
            <div className="flex justify-end gap-2">
              {dialog.kind === "confirm" && (
                <button type="button" className="btn" onClick={() => close(false)}>
                  {dialog.cancelText ?? t("common.cancel")}
                </button>
              )}
              <button
                type="button"
                className={`btn ${isDanger ? "btn-danger" : "btn-primary"}`}
                onClick={() => close(true)}
              >
                {dialog.confirmText ?? (dialog.kind === "confirm" ? t("common.confirm") : t("common.ok"))}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </DialogContext.Provider>
  );
}

export function useDialogs(): DialogApi {
  const ctx = useContext(DialogContext);
  if (!ctx) {
    throw new Error("useDialogs must be used inside DialogProvider");
  }
  return ctx;
}
