"use client";

import { CtxT, useT } from "@/lib/i18n";

type StageState = {
  operation: string;
  status: string;
  overdue?: boolean;
  is_blocked?: boolean;
};

const ORDER = ["cutting", "printing", "sewing", "packaging", "storage_transfer"];

function fallbackLabel(v: string) {
  return String(v || "").replaceAll("_", " ");
}

export function operationLabel(op: string, t: CtxT) {
  if (op === "cutting") return t("dash.cutting");
  if (op === "printing") return t("dash.printing");
  if (op === "sewing") return t("dash.sewing");
  if (op === "packaging") return t("dash.packaging");
  if (op === "storage_transfer") return t("stage.storageTransfer");
  return fallbackLabel(op);
}

export function statusLabel(status: string, t: CtxT) {
  const key = `statusValue.${String(status || "").toLowerCase()}`;
  const translated = t(key);
  if (translated !== key) return translated;
  return fallbackLabel(status);
}

export default function StagePipeline({
  currentStage,
  stages,
  compact = true,
}: {
  currentStage?: string | null;
  stages?: StageState[];
  compact?: boolean;
}) {
  const { t } = useT();
  const byOp = new Map((stages || []).map((s) => [s.operation, s]));
  const currentIdx = currentStage ? ORDER.indexOf(currentStage) : -1;
  return (
    <div className="min-w-[360px]">
      <div className="flex items-center gap-1">
        {ORDER.map((op, idx) => {
          const s = byOp.get(op);
          const isDone = s?.status === "completed" || idx < currentIdx;
          const isCurrent = idx === currentIdx;
          const isBlocked = !!s?.is_blocked;
          const isOverdue = !!s?.overdue;
          const dotCls = isBlocked
            ? "bg-red-600"
            : isOverdue
              ? "bg-amber-500"
              : isCurrent
                ? "bg-orange-500"
                : isDone
                  ? "bg-emerald-600"
                  : "bg-slate-300";
          const lineCls = isDone ? "bg-emerald-500" : "bg-slate-200";
          return (
            <div key={op} className="flex items-center">
              <span
                className={`h-2.5 w-2.5 rounded-full ${dotCls}`}
                title={`${operationLabel(op, t)}${s ? `: ${statusLabel(s.status, t)}` : ""}`}
              />
              {idx < ORDER.length - 1 && <span className={`mx-1 h-[2px] w-10 ${lineCls}`} />}
            </div>
          );
        })}
      </div>
      {!compact && (
        <div className="mt-1 flex gap-2 text-[10px] text-slate-500">
          {ORDER.map((op) => (
            <span key={op} className="inline-block min-w-[58px]">
              {operationLabel(op, t)}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
