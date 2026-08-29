"use client";

import { Plus, Trash2 } from "lucide-react";
import { useT } from "@/lib/i18n";
import { parseNumberInput } from "@/lib/numberInput";
import {
  PAID_OPERATION_FACTORIES,
  type PaidOperation,
  type PaidOperationFactory,
  type SectionCode,
} from "@/lib/modelPaidOperations";

type Props = {
  operations: PaidOperation[];
  visibleFactories: PaidOperationFactory[];
  onAdd: (factory: PaidOperationFactory) => void;
  onUpdate: (id: string, patch: Partial<PaidOperation>) => void;
  onRemove: (id: string) => void;
};

const FACTORY_LABEL_KEYS: Record<PaidOperationFactory, string> = {
  milana: "factory.milana",
  besttex: "factory.besttex",
  eco_cotton: "factory.ecoCotton",
};

export default function PaidOperationsEditor({ operations, visibleFactories, onAdd, onUpdate, onRemove }: Props) {
  const { t } = useT();

  function operationTable(rows: PaidOperation[]) {
    return (
      <div className="overflow-x-auto">
        <table className="table min-w-[1540px]">
          <thead>
            <tr>
              <th className="w-12">{t("common.use")}</th>
              <th>{t("page.modelDetail.sourceOrder")}</th>
              <th>{t("page.modelDetail.operationSection")}</th>
              <th>{t("page.modelDetail.sourceStage")}</th>
              <th>{t("common.code")}</th>
              <th>{t("page.modelDetail.operationName")}</th>
              <th>{t("page.modelDetail.operationDuration")}</th>
              <th>{t("page.modelDetail.ratePerPiece")}</th>
              <th>{t("page.modelDetail.operationCurrency")}</th>
              <th>{t("page.modelDetail.changeDirection")}</th>
              <th>{t("page.modelDetail.finalOperation")}</th>
              <th>{t("page.modelDetail.copies")}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((operation) => (
              <tr key={operation.id}>
                <td><input type="checkbox" className="h-4 w-4" checked={operation.selected} onChange={(event) => onUpdate(operation.id, { selected: event.target.checked })} /></td>
                <td><input className="input w-20" type="number" min={1} step={1} value={operation.sourceOrder ?? ""} onChange={(event) => { const value = parseNumberInput(event.target.value); onUpdate(operation.id, { sourceOrder: value === "" ? undefined : value }); }} /></td>
                <td>
                  <select className="input min-w-[130px]" value={operation.section} onChange={(event) => onUpdate(operation.id, { section: event.target.value as SectionCode })}>
                    <option value="sewing">{t("page.modelDetail.sectionSewing")}</option>
                    <option value="pressing">{t("page.modelDetail.sectionPressing")}</option>
                    <option value="packaging">{t("page.modelDetail.sectionPackaging")}</option>
                  </select>
                </td>
                <td><input className="input min-w-[120px]" value={operation.sourceStage || ""} onChange={(event) => onUpdate(operation.id, { sourceStage: event.target.value })} /></td>
                <td><input className="input min-w-[120px] font-mono" value={operation.code} onChange={(event) => onUpdate(operation.id, { code: event.target.value.toUpperCase() })} /></td>
                <td><input className="input min-w-[190px]" value={operation.name} onChange={(event) => onUpdate(operation.id, { name: event.target.value })} /></td>
                <td><input className="input w-24" type="number" min={0} step="0.01" value={operation.duration || ""} onChange={(event) => onUpdate(operation.id, { duration: event.target.value })} /></td>
                <td><input className="input min-w-[110px]" type="number" min={0} step="0.01" placeholder="0" value={operation.rate} onChange={(event) => onUpdate(operation.id, { rate: event.target.value })} /></td>
                <td><input className="input w-24" value={operation.currency || ""} onChange={(event) => onUpdate(operation.id, { currency: event.target.value })} /></td>
                <td><input className="input min-w-[150px]" value={operation.changeDirection || ""} onChange={(event) => onUpdate(operation.id, { changeDirection: event.target.value })} /></td>
                <td><input type="checkbox" className="h-4 w-4" checked={operation.finalOperation === true} onChange={(event) => onUpdate(operation.id, { finalOperation: event.target.checked })} /></td>
                <td><input className="input w-20" type="number" min={1} value={operation.copies} onChange={(event) => onUpdate(operation.id, { copies: parseNumberInput(event.target.value) })} /></td>
                <td><button type="button" className="icon-btn" title={t("page.modelDetail.removePaidOperation")} onClick={() => onRemove(operation.id)}><Trash2 className="h-4 w-4" /></button></td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={13} className="py-6 text-center text-sm text-slate-500">{t("page.modelDetail.noFactoryPaidOperations")}</td></tr>
            )}
          </tbody>
        </table>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {PAID_OPERATION_FACTORIES.filter((factory) => visibleFactories.includes(factory)).map((factory) => {
        const rows = operations.filter((operation) => operation.sewingFactory === factory);
        const label = t(FACTORY_LABEL_KEYS[factory]);
        return (
          <details key={factory} className="rounded-md border border-[#ded9cc] bg-white" open>
            <summary className="cursor-pointer border-b border-[#ded9cc] bg-[#f8f6ef] px-4 py-3 font-semibold text-[#29251d]">
              {t("page.modelDetail.factorySewingOperations", { factory: label })} ({rows.length})
            </summary>
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3">
              <span className="text-xs text-[#716a5c]">{t("page.modelDetail.factoryOperationsHint", { factory: label })}</span>
              <button type="button" className="btn" onClick={() => onAdd(factory)}>
                <Plus className="h-4 w-4" />
                <span>{t("page.modelDetail.addPaidOperation")}</span>
              </button>
            </div>
            {operationTable(rows)}
          </details>
        );
      })}
    </div>
  );
}
