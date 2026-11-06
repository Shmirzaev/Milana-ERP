"use client";

import { Check, Clock3, Minus, Circle, AlertTriangle } from "lucide-react";
import { useT } from "@/lib/i18n";
import { processTimeline, type TimelineStage } from "@/lib/processTimeline";
import { operationLabel } from "@/components/StagePipeline";

const tones = {
  green: "border-emerald-600 bg-emerald-600 text-white",
  yellow: "border-amber-500 bg-amber-500 text-white",
  gray: "border-[#b8b8b2] bg-white text-[#a2a29b]",
  red: "border-red-600 bg-red-600 text-white",
};

export function ProcessTimelineLegend() {
  const { t } = useT();
  return (
    <div className="mb-4 flex flex-wrap justify-end gap-x-5 gap-y-2 text-xs text-[#56503f]">
      {(["green", "yellow", "gray"] as const).map(tone => (
        <span key={tone} className="inline-flex items-center gap-2">
          <span aria-hidden="true" className={`h-3 w-3 rounded-full border ${tones[tone]}`} />
          {t(`processTimeline.legend.${tone}`)}
        </span>
      ))}
    </div>
  );
}

export default function ProcessTimeline({ stages, showHeadings = true }: { stages: TimelineStage[]; showHeadings?: boolean }) {
  const { t } = useT();
  const items = processTimeline(stages);
  return (
    <ol className="grid min-w-[610px] grid-cols-5" aria-label={t("page.processes.stagesHeader")}>
      {items.map((item, index) => {
        const { operation, stage, state, tone, received, output, ready, planned } = item;
        const Icon = tone === "green" ? Check : tone === "yellow" ? Clock3 : tone === "red" ? AlertTriangle : state === "skipped" ? Minus : Circle;
        return (
          <li key={operation} className="min-w-0 text-center" data-stage={operation} data-state={state}>
            {showHeadings && <div className="mb-3 px-1 text-xs font-medium text-[#2c2920]">{operationLabel(operation, t)}</div>}
            <div className="relative mb-2 flex h-10 items-center justify-center">
              {index > 0 && <span aria-hidden="true" className="absolute left-0 right-1/2 h-px bg-[#d8d8d1]" />}
              {index < items.length - 1 && <span aria-hidden="true" className="absolute left-1/2 right-0 h-px bg-[#d8d8d1]" />}
              <span aria-hidden="true" className={`relative z-[1] flex h-10 w-10 items-center justify-center rounded-full border-2 ring-[6px] ring-white ${tones[tone]} ${state === "skipped" ? "!border-[#e4e4df] !bg-[#e4e4df]" : ""}`}>
                <Icon className={tone === "gray" && state !== "skipped" ? "h-3 w-3 fill-current" : "h-5 w-5"} strokeWidth={2} />
              </span>
            </div>
            <div className="space-y-1 px-1 text-xs leading-5">
              {operation === "sewing" && stage ? (
                <>
                  <div className="font-medium text-[#2c2920]">
                    {state === "accepted" ? t("processTimeline.acceptedQuantity", { quantity: received }) : t(`processTimeline.state.${state}`)}
                  </div>
                  {state !== "accepted" && (ready > 0 || received > 0) && (
                    <div className="text-[#65655e]">{t("processTimeline.readyAccepted", { ready, received })}</div>
                  )}
                  <div className="text-[#65655e]">{t("processTimeline.sewnQuantity", { quantity: output, total: Math.max(received, ready) || planned })}</div>
                </>
              ) : (
                <>
                  {stage && (output > 0 || state === "completed" || state === "partial") && <div className="font-medium tabular-nums text-[#2c2920]">{output} / {planned}</div>}
                  <div className={tone === "red" ? "text-red-700" : "text-[#65655e]"}>{t(`processTimeline.state.${state}`)}</div>
                </>
              )}
              {stage?.is_blocked && stage.block_reason && <div className="text-red-700">{stage.block_reason}</div>}
              {stage?.overdue && state !== "completed" && <div className="text-red-700">{t("page.processes.overdue")}</div>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
