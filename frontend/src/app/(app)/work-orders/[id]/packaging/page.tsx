"use client";
import { localizeError } from "@/lib/errorMessages";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import FirstGradePackaging from "@/components/FirstGradePackaging";
import UslugaPackaging from "@/components/UslugaPackaging";
import PendingPackageWorkflow from "@/components/PendingPackageWorkflow";
import PackageQrSection from "@/components/PackageQrSection";
import { postPackageWorkflow, type PackagePrintRun } from "@/lib/packageWorkflow";
import PageHeader from "@/components/PageHeader";
import { statusLabel } from "@/components/StagePipeline";
import WorkOrderProductInfo from "@/components/WorkOrderProductInfo";
import PackageBatchBreakdownEditor from "@/components/PackageBatchBreakdownEditor";
import { flexibleBatchTraceText, packageBatchTraceText, packageTracePlanKey, traceItems, tracePackagePlans, type BatchTraceDraft } from "@/lib/packageBatchTrace";
import { packagingAvailabilityText } from "@/lib/packagingAvailabilityText";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { numberOrFallback, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import { orderReference } from "@/lib/orderRef";
import { directPackagingDamageText, packagingDamageActionText, multiNastilText, planSelectedNastils, type PackagePlan, type PackagePlanItem, type PackageSourceBalances } from "@/lib/multiNastilPackaging";

type PackageRecipeItem = { size: string; quantity: NumberInputValue };

function trimPackageItemsToQuantity(items: PackagePlanItem[], targetQty: number) {
  let remaining = Math.max(0, Math.floor(Number(targetQty || 0)));
  const out: PackagePlanItem[] = [];
  for (const item of items) {
    if (remaining <= 0) break;
    const quantity = Math.min(remaining, Math.max(0, Number(item.quantity || 0)));
    if (quantity > 0) {
      out.push({ ...item, quantity });
      remaining -= quantity;
    }
  }
  return out;
}

function parseOptionalDecimalInput(value: string | number | null | undefined): number | null {
  const normalized = String(value ?? "").replace(",", ".").trim();
  if (!normalized) return null;
  return Number(normalized);
}

export default function PackagingPage() {
  const { t, lang } = useT();
  const multiCopy = multiNastilText[lang];
  const damageCopy = directPackagingDamageText[lang];
  const damageActionCopy = packagingDamageActionText[lang];
  const { me } = useMe();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { mutate: mutateCache } = useSWRConfig();
  const { data: wo, mutate: mutateWo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po, mutate: mutatePo } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: batchProgress, mutate: mutateBatchProgress } = useSWR<any>(
    wo ? `/api/work-orders/${id}/packaging-batch-progress` : null,
    fetcher,
  );
  const { data: packageSources, error: packageSourcesError, isLoading: packageSourcesLoading, mutate: mutatePackageSources } = useSWR<PackageSourceBalances>(
    wo && po?.source_type !== "usluga" && can(me, "packaging.packages") ? `/api/packages/sources/${id}` : null,
    fetcher,
  );
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/${po.source_type === "usluga" ? "usluga/" : ""}models/${po.model_id}` : null, fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);

  const [selectedBatchId, setSelectedBatchId] = useState(0);
  const [pkgItems, setPkgItems] = useState<PackageRecipeItem[]>([{ size: "M", quantity: 60 }]);
  const [capacity, setCapacity] = useState<NumberInputValue>(60);
  const [weightKg, setWeightKg] = useState("");
  const [packageWeights, setPackageWeights] = useState<string[]>([]);
  const [chosenColor, setColor] = useState("");
  const color = chosenColor || String(po?.items?.find((item: any) => item.color)?.color || "");
  const [copies, setCopies] = useState<NumberInputValue>(1);
  const [copiesTouched, setCopiesTouched] = useState(false);
  const [mergeAcrossBatches, setMergeAcrossBatches] = useState(false);
  const [selectedMergeBatchIds, setSelectedMergeBatchIds] = useState<number[]>([]);
  const [packOnlyFullPackages, setPackOnlyFullPackages] = useState(false);
  const [pkgNotice, setPkgNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [pkg, setPkg] = useState<any>(null);
  const [packageQrRefreshKey, setPackageQrRefreshKey] = useState(0);
  const [damagedQty, setDamagedQty] = useState<NumberInputValue>("");
  const [batchTraceDraft, setBatchTraceDraft] = useState<{ key: string; values: BatchTraceDraft }>({ key: "", values: {} });
  const canEditBreakdown = can(me, "*", "planning.production", "cutting.records", "packaging.records");
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const batchItems = useMemo(() => (
    Array.isArray(batchProgress?.items) ? batchProgress.items : []
  ), [batchProgress?.items]);
  const orderColorItems = useMemo(() => {
    const allItems = po?.items || [];
    const rows = allItems.filter((it: any) => String(it?.color || "").toLowerCase() === String(color || "").toLowerCase());
    const source = rows.length > 0 ? rows : allItems;
    const bySize = new Map<string, number>();
    for (const it of source) {
      const size = String(it?.size || "-").trim();
      if (!size || size === "-") continue;
      bySize.set(size, (bySize.get(size) || 0) + Math.max(0, Number(it?.planned_quantity || 0)));
    }
    return Array.from(bySize.entries()).map(([size, planned_quantity]) => ({ size, planned_quantity }));
  }, [po?.items, color]);

  const selectedSource = isAlreadyBatched
    ? packageSources?.items.find(row => row.id === selectedBatchId)
    : packageSources?.unbatched_source;
  const packageableColorQty = Math.max(0, Number(selectedSource?.available_to_package ?? 0) - Number(damagedQty || 0));
  const colorOrderItems = orderColorItems;
  const suggestedCopies = 1;

  const autoPackageItems = useMemo(() => {
    const cap = Math.max(1, Number(capacity || 0));
    const rows = colorOrderItems
      .map((it: any) => ({ size: String(it?.size || "-"), qty: Math.max(0, Number(it?.planned_quantity || 0)) }))
      .filter((it: any) => it.size && it.size !== "-");
    if (!rows.length) return [{ size: "M", quantity: cap }];

    const n = rows.length;
    const total = rows.reduce((s: number, r: any) => s + r.qty, 0);
    const out = rows.map((r: any) => ({ size: r.size, quantity: 0, _weight: r.qty }));

    if (cap >= n) {
      for (const o of out) o.quantity = 1;
      let remaining = cap - n;
      if (remaining > 0) {
        if (total > 0) {
          const shares = out.map((o) => ({
            size: o.size,
            base: Math.floor((remaining * o._weight) / total),
            rem: ((remaining * o._weight) / total) - Math.floor((remaining * o._weight) / total),
          }));
          let used = 0;
          for (const o of out) {
            const sh = shares.find((s) => s.size === o.size)!;
            o.quantity += sh.base;
            used += sh.base;
          }
          let left = remaining - used;
          const ranked = [...shares].sort((a, b) => b.rem - a.rem);
          let idx = 0;
          while (left > 0) {
            const target = ranked[idx % ranked.length];
            const o = out.find((x) => x.size === target.size)!;
            o.quantity += 1;
            left -= 1;
            idx += 1;
          }
        } else {
          let i = 0;
          while (remaining > 0) {
            out[i % out.length].quantity += 1;
            remaining -= 1;
            i += 1;
          }
        }
      }
    } else {
      const ranked = [...out].sort((a, b) => b._weight - a._weight);
      for (let i = 0; i < cap; i += 1) ranked[i].quantity += 1;
    }

    return out.filter(item => item.quantity > 0).map(({ size, quantity }) => ({ size, quantity }));
  }, [colorOrderItems, capacity]);

  const packingPreview = useMemo(() => {
    const perPackage = pkgItems.map(it => ({ size: String(it.size || "").trim(), qty: Number(it.quantity) }));
    const packageTotal = perPackage.reduce((sum, item) => sum + item.qty, 0);
    const empty = { fullCount: 0, notFullCount: 0, packageTotal: 0,
      partialPackages: [] as Array<{ index: number; items: Array<{ size: string; qty: number }>; total: number }> };
    if (!perPackage.length || perPackage.some(it => !it.size || !Number.isInteger(it.qty) || it.qty <= 0)
      || !Number.isInteger(Number(copies)) || Number(copies) < 1 || Number(copies) > 200) return empty;
    const fullCount = Math.min(Number(copies), Math.floor(packageableColorQty / packageTotal));
    const remaining = packageableColorQty - fullCount * packageTotal;
    const partialQty = Number(copies) > fullCount ? Math.min(remaining, packageTotal) : 0;
    const partialItems = trimPackageItemsToQuantity(perPackage.map(it => ({ model_id: 0, color, size: it.size, quantity: it.qty })), partialQty);
    const partialPackages = partialQty > 0 ? [{ index: fullCount + 1,
      items: partialItems.map(it => ({ size: it.size, qty: it.quantity })), total: partialQty }] : [];
    return { fullCount, notFullCount: partialPackages.length, packageTotal, partialPackages };
  }, [pkgItems, packageableColorQty, copies, color]);

  const basePackageItems = useMemo<PackagePlanItem[]>(() => (
    pkgItems.some(item => !item.size.trim() || !Number.isInteger(Number(item.quantity)) || Number(item.quantity) <= 0) ? [] : pkgItems
      .map((i) => ({
        model_id: Number(po?.model_id || 0),
        color,
        size: String(i.size || "").trim(),
        quantity: Math.max(0, Number(i.quantity || 0)),
      }))
      .filter((i) => i.model_id > 0 && i.size && i.quantity > 0)
  ), [color, pkgItems, po?.model_id]);

  const standardPackagePlans = useMemo<PackagePlan[]>(() => {
    const plans: PackagePlan[] = [];
    for (let i = 0; i < packingPreview.fullCount; i += 1) {
      plans.push({ items: basePackageItems });
    }
    if (!packOnlyFullPackages) {
      for (const partial of packingPreview.partialPackages) {
        const items = partial.items
          .map((i) => ({
            model_id: Number(po?.model_id || 0),
            color,
            size: String(i.size || "").trim(),
            quantity: Math.max(0, Number(i.qty || 0)),
          }))
          .filter((i) => i.model_id > 0 && i.size && i.quantity > 0);
        if (items.length > 0) plans.push({ items });
      }
    }
    return plans;
  }, [basePackageItems, color, packOnlyFullPackages, packingPreview.fullCount, packingPreview.partialPackages, po?.model_id]);

  const batchPackageAvailability = useMemo(() => (
    (Array.isArray(packageSources?.items) ? packageSources.items : [])
      .map((row) => {
        const available = Math.max(0, Number(row?.available_to_package || 0));
        return {
          id: Number(row?.id || 0),
          label: formatBatchLabel(row, po?.id),
          available,
          actualSizeVerified: row.actual_size_verified,
          sizeBalances: row.size_balances,
        };
      })
      .filter((row) => row.id > 0)
  ), [packageSources?.items, po?.id]);

  const selectedMergeBatchCount = batchPackageAvailability.filter((source) => source.available > 0 && selectedMergeBatchIds.includes(source.id)).length;
  const mergedPackingPlan = useMemo(() => planSelectedNastils(
    basePackageItems, batchPackageAvailability, isAlreadyBatched ? selectedMergeBatchIds : [],
    Math.min(200, Math.max(0, Math.floor(Number(copies || 0)))),
  ), [basePackageItems, batchPackageAvailability, copies, isAlreadyBatched, selectedMergeBatchIds]);

  const mergedPartialItems = useMemo(
    () => trimPackageItemsToQuantity(basePackageItems, mergedPackingPlan.pendingQty),
    [basePackageItems, mergedPackingPlan.pendingQty],
  );

  const packagePlans = useMemo<PackagePlan[]>(() => {
    if (!Number.isInteger(Number(copies)) || Number(copies) < 1 || Number(copies) > 200) return [];
    if (!mergeAcrossBatches) return standardPackagePlans;
    if (packOnlyFullPackages || mergedPackingPlan.pendingQty <= 0 || mergedPartialItems.length === 0) {
      return mergedPackingPlan.plans.slice(0, Math.max(0, Math.floor(Number(copies || 0))));
    }
    return [
      ...mergedPackingPlan.plans,
      {
        items: mergedPartialItems,
        batch_allocations: mergedPackingPlan.pendingAllocations,
      },
    ].slice(0, Math.max(0, Math.floor(Number(copies || 0))));
  }, [
    copies,
    mergeAcrossBatches,
    mergedPackingPlan.pendingAllocations,
    mergedPackingPlan.pendingQty,
    mergedPackingPlan.plans,
    mergedPartialItems,
    packOnlyFullPackages,
    standardPackagePlans,
  ]);
  const manualMixedAttribution = mergeAcrossBatches && packagePlans.some(plan => traceItems(plan.items).length > 1);
  const selectedTraceSources = batchPackageAvailability.filter(source => source.available > 0 && selectedMergeBatchIds.includes(source.id));
  const sourceTraceBudgets = manualMixedAttribution ? Object.fromEntries(selectedTraceSources.map(source => [source.id, source.available])) : undefined;
  const sourceSizeTraceBudgets = manualMixedAttribution ? Object.fromEntries(selectedTraceSources.filter(source => source.actualSizeVerified === true).map(source => [source.id,
    Object.fromEntries((source.sizeBalances ?? []).map(row => [row.size.trim(), row.remaining ?? 0])),
  ])) : undefined;
  const attributionPlans = manualMixedAttribution ? packagePlans.map(plan => ({ ...plan,
    batch_allocations: selectedTraceSources.map(source => ({ production_batch_id: source.id, quantity: source.available, label: source.label })),
  })) : packagePlans;
  const tracePlanKey = packageTracePlanKey(attributionPlans);
  const traceDraft = batchTraceDraft.key === tracePlanKey ? batchTraceDraft.values : {};
  const tracedPackages = tracePackagePlans(attributionPlans, traceDraft, sourceTraceBudgets, sourceSizeTraceBudgets);
  const selectedSourcePreview = (tracedPackages.valid ? tracedPackages.plans : []).slice(0, 3).map(plan =>
    (plan.batch_allocations || []).map(source => `${source.label}: ${source.quantity}`).join(" + "),
  ).filter(Boolean);
  const packageWeightCount = packagePlans.length;
  const createsMergedPartial = !packOnlyFullPackages && Number(copies) > mergedPackingPlan.plans.length;
  const selectedOutputRemaining = Math.max(0, (mergeAcrossBatches ? mergedPackingPlan.totalAvailable : packageableColorQty)
    - packagePlans.reduce((sum, plan) => sum + plan.items.reduce((quantity, item) => quantity + item.quantity, 0), 0));

  useEffect(() => {
    setPkgItems(autoPackageItems);
  }, [autoPackageItems]);

  useEffect(() => {
    if (!copiesTouched) setCopies(suggestedCopies);
  }, [copiesTouched, suggestedCopies]);

  useEffect(() => {
    setPackageWeights((prev) => (
      Array.from({ length: packageWeightCount }, (_, index) => prev[index] ?? weightKg ?? "")
    ));
  }, [packageWeightCount, weightKg]);

  useEffect(() => {
    if (!isAlreadyBatched || !packageSources?.items.length) return;
    // Revalidation must not move a draft (especially damage) to another Nastil.
    // A removed selection stays invalid until the operator chooses a new one.
    setSelectedBatchId(previous => previous || (packageSources.items.find(row => row.available_to_package > 0)?.id ?? packageSources.items[0].id));
  }, [isAlreadyBatched, packageSources]);

  async function refreshPackagingOutputs() {
    await Promise.all([mutateBatchProgress(), mutatePackageSources(), mutateWo(), mutatePo()]);
    const sizePath = `/api/packages/first-grade/size-entry/${po?.id}`;
    await mutateCache((key) => typeof key === "string" && (key === sizePath || key.startsWith(`${sizePath}?`)));
    setPackageQrRefreshKey((prev) => prev + 1);
  }

  async function saveBreakdown(items: Array<{ id?: number | null; color: string; size: string; planned_quantity: number }>) {
    if (!po?.id) return;
    await api.put(`/api/production-orders/${po.id}/breakdown`, { items });
    await refreshPackagingOutputs();
  }

  async function recordDamageOnly() {
    if (isCreating || !me) return;
    setPkgNotice(null); setIsCreating(true);
    try {
      const quantity = Number(damagedQty || 0);
      if (mergeAcrossBatches || packageSourcesLoading || packageSourcesError || !selectedSource
        || !Number.isInteger(quantity) || quantity <= 0 || quantity > selectedSource.available_input_qty) {
        throw new Error(damageCopy.invalid);
      }
      await postPackageWorkflow("/api/packages/record-damage", {
        work_order_id: id, production_batch_id: selectedBatchId || null, damaged_qty: quantity,
      }, me.id);
      setDamagedQty("");
      setPkgNotice({ type: "success", text: damageActionCopy.saved });
      try { await refreshPackagingOutputs(); }
      catch (error: any) { setPkgNotice({ type: "success", text: `${damageActionCopy.saved} ${error.message}` }); }
    } catch (error: any) {
      setPkgNotice({ type: "error", text: error.message });
    } finally { setIsCreating(false); }
  }

  async function createPkg(e: React.FormEvent) {
    e.preventDefault();
    if (isCreating) return;
    setPkgNotice(null);
    setIsCreating(true);
    try {
      if (!Number.isInteger(Number(copies)) || Number(copies) < 1 || Number(copies) > 200) {
        throw new Error(multiCopy.packCount);
      }
      if (packageSourcesLoading || packageSourcesError || !packageSources) throw new Error(multiCopy.noOutput);
      if (!mergeAcrossBatches && isAlreadyBatched && !selectedSource) throw new Error(multiCopy.chooseBatch);
      if (mergeAcrossBatches && selectedMergeBatchCount < 2) throw new Error(multiCopy.chooseTwo);
      if (!tracedPackages.valid) throw new Error(manualMixedAttribution ? flexibleBatchTraceText[lang].invalid : packageBatchTraceText[lang].invalid);
      if (!mergeAcrossBatches && (!Number.isInteger(Number(damagedQty || 0)) || Number(damagedQty || 0) < 0
        || Number(damagedQty || 0) > Number(selectedSource?.available_input_qty || 0))) throw new Error(damageCopy.invalid);
      const weightValues = packagePlans.map((_, index) => {
        return parseOptionalDecimalInput(packageWeights[index]);
      });
      const invalidWeight = weightValues.some((value) => value !== null && (!Number.isFinite(value) || value < 0));
      if (invalidWeight) {
        throw new Error(t("page.packaging.invalidWeight"));
      }
      const payloadBase = {
        production_order_id: wo?.production_order_id,
        sales_order_id: po?.sales_order_id || null,
        model_id: po?.model_id,
        color,
        package_type: "bag",
        capacity: numberOrFallback(capacity, 1),
        weight_kg: null,
        production_batch_id: mergeAcrossBatches ? null : selectedBatchId || null,
      };
      if (packagePlans.length === 0) {
        throw new Error(localizeError("No package items to create."));
      }

      const run = await postPackageWorkflow<PackagePrintRun>("/api/packages/print-runs/create-packages", {
          work_order_id: id,
          ...(!mergeAcrossBatches && Number(damagedQty) > 0 ? { damaged_qty: Number(damagedQty) } : {}),
          packages: tracedPackages.plans.map((plan, index) => ({
            ...payloadBase, weight_kg: weightValues[index], items: plan.items,
            batch_allocations: plan.batch_allocations || [],
          })),
        }, me!.id);
        setPkg({ id: run.package_ids[0], package_no: run.run_no, barcode: "bulk" });
        setDamagedQty("");
        setBatchTraceDraft({ key: "", values: {} });
        setPkgNotice({ type: "success", text: t("page.packaging.bulkCreatedWithFirst", { count: run.count, no: run.run_no }) });
        // Creation already succeeded: a blocked print window must not suggest
        // repeating package creation. The saved run remains available below.
        try {
          await refreshPackagingOutputs();
          await api.openLabel(`/api/packages/print-runs/${run.id}/label`);
        }
        catch (printError: any) { setPkgNotice({ type: "success", text: `${run.run_no}: ${printError.message}` }); }
    } catch (e: any) {
      setPkgNotice({ type: "error", text: e?.message || t("page.packaging.createFailed") });
    } finally {
      setIsCreating(false);
    }
  }

  const orderNo = orderReference({
    order_no: so?.order_no || po?.order_no || wo?.order_no,
    sales_order_no: po?.sales_order_no || wo?.sales_order_no,
    production_no: po?.production_no || wo?.production_no,
    production_order_id: wo?.production_order_id,
  }, `#${id}`);

  if (po?.source_type === "usluga") return <div>
    <PageHeader title={t("page.packaging.title", { id, orderNo })} />
    <WorkOrderProductInfo t={t} so={so} po={po} wo={wo} model={model} customerName={po.service_customer_name}
      statusText={wo ? statusLabel(wo.status, t) : "-"} compact />
    <UslugaPackaging workOrderId={id} onSaved={refreshPackagingOutputs} />
  </div>;

  return (
    <div>
      <PageHeader title={t("page.packaging.title", { id, orderNo })} subtitle={t("page.packaging.subtitle")} />
      <WorkOrderProductInfo
        t={t}
        so={so}
        po={po}
        wo={wo}
        model={model}
        customerName={so?.customer_id ? (customerMap.get(so.customer_id) || `#${so.customer_id}`) : null}
        statusText={wo ? statusLabel(wo.status, t) : "-"}
        compact
        canEditBreakdown={canEditBreakdown}
        onSaveBreakdown={saveBreakdown}
      />
      <p className="mb-4 text-sm text-slate-600">{multiCopy.directHint}</p>
      <div className="mb-4">
        {isAlreadyBatched && (
          <div className="card p-4">
            <div className="mb-2 text-base font-semibold">{t("batch.managedInsideWorkOrder")}</div>
            <div className="overflow-x-auto">
              <table className="table text-sm">
                <thead>
                  <tr>
                    <th>{t("field.batch")}</th>
                    <th>{t("field.sewn")}</th>
                    <th>{packagingAvailabilityText[lang].recordedOutput}</th>
                    <th>{t("field.damaged")}</th>
                    <th>{t("field.remaining")}</th>
                    <th>{t("page.processes.progress")}</th>
                  </tr>
                </thead>
                <tbody>
                  {batchItems.map((row: any) => (
                    <tr key={row.id}>
                      <td>
                        <div className="font-medium">{formatBatchLabel(row, po?.id)}</div>
                        <div className="text-xs text-slate-500">{formatBatchSerial(row, po?.id)}</div>
                      </td>
                      <td>{row.sewing_output_qty}</td>
                      <td>{row.packed_qty}</td>
                      <td>{row.damaged_qty}</td>
                      <td>{packageSources?.items.find(source => source.id === Number(row.id))?.available_to_package ?? row.available_input_qty}</td>
                      <td>{row.progress_pct}%</td>
                    </tr>
                  ))}
                  {batchItems.length === 0 && (
                    <tr>
                      <td colSpan={6} className="text-slate-500">{t("batch.noProgressYet")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="mb-4">
        {po && !po.sales_order_id && po.source_type !== "usluga" && !mergeAcrossBatches && (!isAlreadyBatched || selectedSource) && <FirstGradePackaging key={`${po.id}:${selectedBatchId}:${color}`} productionOrderId={po.id} workOrderId={id} batchId={selectedBatchId || undefined} modelId={po.model_id} color={color} onChanged={refreshPackagingOutputs} />}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        {can(me, "packaging.packages") && <form onSubmit={createPkg} className="card space-y-3 p-6">
          <h3 className="font-medium">{t("page.packaging.newPackage")}</h3>
          {isAlreadyBatched && !mergeAcrossBatches && <label className="block text-sm">
            {t("batch.orderBatch")}
            <select className="input mt-1" aria-label={t("batch.orderBatch")} value={selectedBatchId} disabled={isCreating || packageSourcesLoading}
              onChange={event => { setSelectedBatchId(Number(event.target.value)); setDamagedQty(""); setCopiesTouched(false); }}>
              <option value={0}>{t("batch.selectBatch")}</option>
              {(packageSources?.items || []).map(source => <option key={source.id} value={source.id}>
                {formatBatchLabel(source, po?.id)} ({multiCopy.available}: {source.available_to_package})
              </option>)}
            </select>
          </label>}
          <p className="text-sm">{multiCopy.available}: {mergeAcrossBatches ? mergedPackingPlan.totalAvailable : packageableColorQty}</p>
          {packageSourcesLoading && <p role="status" className="text-sm">{t("common.loading")}</p>}
          {packageSourcesError && <p role="alert" className="text-sm text-red-700">{packageSourcesError.message}</p>}
          {!packageSourcesLoading && !packageSourcesError && packageableColorQty === 0 && !mergeAcrossBatches && <p className="text-sm">{multiCopy.noOutput}</p>}
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className="label">{t("field.color")}</label>
              <input className="input" aria-label={t("field.color")} disabled={isCreating} value={color} onChange={(e) => setColor(e.target.value)} />
            </div>
            <div>
              <label className="label">{t("field.capacity")}</label>
              <input className="input" aria-label={t("field.capacity")} disabled={isCreating} type="number" min={1} step={1} value={capacity} onChange={(e) => setCapacity(parseNumberInput(e.target.value))} />
            </div>
            <div>
              <label className="label">{t("page.packaging.defaultWeightKg")}</label>
              <input
                className="input"
                aria-label={t("page.packaging.defaultWeightKg")}
                disabled={isCreating}
                min={0}
                step="0.001"
                type="number"
                value={weightKg}
                onChange={(e) => setWeightKg(e.target.value)}
              />
            </div>
            <div>
              <label className="label">{multiCopy.count}</label>
              <input
                className="input"
                aria-label={multiCopy.count}
                min={1}
                max={200}
                step={1}
                type="number"
                disabled={isCreating}
                value={copies}
                onChange={(e) => {
                  setCopiesTouched(true);
                  setCopies(parseNumberInput(e.target.value));
                }}
              />
            </div>
          </div>
          {!mergeAcrossBatches && <label className="block text-sm">
            {damageCopy.label}
            <input className="input mt-1" aria-label={damageCopy.label} type="number" min={0}
              max={selectedSource?.available_input_qty ?? 0} step={1} disabled={isCreating}
              value={damagedQty} onChange={event => setDamagedQty(parseNumberInput(event.target.value))} />
            <span className="mt-1 block text-xs text-slate-500">{damageCopy.hint}</span>
          </label>}
          <div className="text-xs text-slate-500">
            {multiCopy.sizeHint}
          </div>
          <p className="text-sm">{multiCopy.remaining}: {selectedOutputRemaining}</p>
          <label className="flex items-start gap-2 text-sm">
            <input className="mt-1" type="checkbox" checked={!packOnlyFullPackages}
              disabled={isCreating} onChange={event => setPackOnlyFullPackages(!event.target.checked)} />
            <span>{multiCopy.partial}<span className="mt-1 block text-xs text-slate-500">{multiCopy.partialHint}</span></span>
          </label>
          {isAlreadyBatched && (
            <div className="rounded-md border border-[#ecebe3] bg-[#faf9f4] px-3 py-2 text-sm">
              <label className="flex items-start gap-2">
                <input
                  className="mt-1"
                  type="checkbox"
                  checked={mergeAcrossBatches}
                  disabled={isCreating}
                  onChange={(e) => { setMergeAcrossBatches(e.target.checked); setDamagedQty(""); }}
                />
                <span>
                  <span className="font-medium">{multiCopy.title}</span>
                  <span className="mt-1 block text-xs text-slate-500">{multiCopy.hint}</span>
                </span>
              </label>
              {mergeAcrossBatches && <>
              <div className="mt-3 overflow-x-auto"><table className="table text-sm">
                <thead><tr><th>{multiCopy.select}</th><th>{multiCopy.nastil}</th><th>{multiCopy.available}</th></tr></thead>
                <tbody>{batchPackageAvailability.map(source => <tr key={source.id}>
                  <td><input type="checkbox" aria-label={`${multiCopy.select} ${source.label}`}
                    disabled={isCreating || source.available <= 0} checked={selectedMergeBatchIds.includes(source.id)}
                    onChange={event => setSelectedMergeBatchIds(previous => event.target.checked
                      ? [...new Set([...previous, source.id])] : previous.filter(batchId => batchId !== source.id))} /></td>
                  <td>{source.label}
                    {source.actualSizeVerified === true && <p className="mt-1 text-xs text-slate-600">{packageBatchTraceText[lang].available}: {(source.sizeBalances ?? []).map(row => `${row.size}: ${row.remaining ?? "?"}`).join(" / ")}</p>}
                    {source.actualSizeVerified === false && <p className="mt-1 text-xs text-slate-600">{packageBatchTraceText[lang].actualUnknown}</p>}
                  </td><td>{source.available}</td>
                </tr>)}</tbody>
              </table></div>
              <p className="mt-2 text-xs">{multiCopy.selected}: {selectedMergeBatchCount} · {multiCopy.available}: {mergedPackingPlan.totalAvailable}</p>
              {selectedMergeBatchCount < 2 && <p className="mt-1 text-xs" role="status">{multiCopy.chooseTwo}</p>}
              {packageSourcesLoading && <p className="mt-1 text-xs">{t("common.loading")}</p>}
              {packageSourcesError && <p role="alert" className="mt-1 text-xs text-red-700">{packageSourcesError.message}</p>}
              {!packageSourcesLoading && !packageSourcesError && !batchPackageAvailability.some(source => source.available > 0) && <p className="mt-1 text-xs">{multiCopy.noOutput}</p>}
              <div className="mt-2 text-xs text-slate-600">
                {`${t("page.packaging.mergeFullPackages", { count: Math.min(packagePlans.length, mergedPackingPlan.plans.length) })} · ${t("page.packaging.mergePending", { count: selectedOutputRemaining })}`}
              </div>
              {selectedSourcePreview.length > 0 && (
                <div className="mt-1 text-xs text-slate-600">
                  {t("page.packaging.mergeSources")}: {selectedSourcePreview.join(" | ")}
                </div>
              )}
              </>}
            </div>
          )}

          <h4 className="text-sm font-medium">{t("page.packaging.sizesInPackage")}</h4>
          <div className="overflow-x-auto">
            <table className="table">
            <thead>
              <tr>
                <th>{t("field.size")}</th>
                <th>{t("field.qty")}</th>
                <th>{t("field.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {pkgItems.map((it, i) => (
                <tr key={i}>
                  <td><input className="input" value={it.size} onChange={(e) => setPkgItems(pkgItems.map((x, j) => (j === i ? { ...x, size: e.target.value } : x)))} /></td>
                  <td><input className="input" type="number" value={it.quantity} onChange={(e) => setPkgItems(pkgItems.map((x, j) => (j === i ? { ...x, quantity: parseNumberInput(e.target.value) } : x)))} /></td>
                  <td><button type="button" className="btn btn-danger" onClick={() => setPkgItems(pkgItems.filter((_, j) => j !== i))}>{t("btn.remove")}</button></td>
                </tr>
              ))}
            </tbody>
            </table>
          </div>
          <button type="button" className="btn" onClick={() => setPkgItems([...pkgItems, { size: "L", quantity: "" }])}>{t("btn.addSize")}</button>
          <div className="text-sm text-slate-500">{t("page.packaging.totalLine", { n: pkgItems.reduce((s, i) => s + Number(i.quantity || 0), 0) })}</div>

          <PackageBatchBreakdownEditor plans={attributionPlans} draft={traceDraft} lang={lang} disabled={isCreating} sourceBudgets={sourceTraceBudgets} sourceSizeBudgets={sourceSizeTraceBudgets}
            onChange={values => setBatchTraceDraft({ key: tracePlanKey, values })} />
          <button className="btn btn-primary" disabled={isCreating || packageSourcesLoading || !!packageSourcesError || packagePlans.length === 0 || !tracedPackages.valid}>
            {isCreating ? t("common.creating") : `${multiCopy.create} (${packagePlans.length})`}
          </button>
          {!mergeAcrossBatches && Number(damagedQty) > 0 && <button type="button" className="btn" disabled={isCreating || packageSourcesLoading || !!packageSourcesError} onClick={recordDamageOnly}>
            {damageActionCopy.save}
          </button>}
          {pkgNotice && (
            <div
              className={`rounded-md border px-3 py-2 text-sm ${
                pkgNotice.type === "success"
                  ? "border-green-300 bg-green-50 text-green-700"
                  : "border-red-300 bg-red-50 text-red-700"
              }`}
            >
              {pkgNotice.text}
            </div>
          )}
        </form>}

        <div className="card p-6">
          <h3 className="font-medium">{multiCopy.planned}</h3>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs text-slate-500">{t("page.packaging.fullPackages")}</div>
              <div className="text-xl font-semibold">{mergeAcrossBatches ? Math.min(packagePlans.length, mergedPackingPlan.plans.length) : packingPreview.fullCount}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs text-slate-500">{t("page.packaging.notFullPackages")}</div>
              <div className="text-xl font-semibold">
                {mergeAcrossBatches ? (createsMergedPartial && mergedPackingPlan.pendingQty > 0 ? 1 : 0) : (packOnlyFullPackages ? 0 : packingPreview.notFullCount)}
              </div>
            </div>
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs text-slate-500">{t("page.packaging.packCapacity")}</div>
              <div className="text-xl font-semibold">{packingPreview.packageTotal}</div>
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">
            {damageCopy.preview}
          </div>
          <div className="mt-3 space-y-2">
            {mergeAcrossBatches ? (
              mergedPackingPlan.pendingQty > 0 ? (
                <div className="rounded-md border border-[#ecebe3] px-3 py-2">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-sm font-medium">
                      {!createsMergedPartial ? t("page.packaging.pendingLeftover") : t("page.packaging.finalPartialPackage")} - {mergedPackingPlan.pendingQty}/{packingPreview.packageTotal}
                    </div>
                    <span className="badge">{!createsMergedPartial ? t("page.packaging.pendingNotCreated") : t("page.packaging.willBeCreated")}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-600">
                    {!createsMergedPartial ? t("page.packaging.pendingLeftoverHint") : t("page.packaging.partialWarehouseHint")}
                  </div>
                  {createsMergedPartial && mergedPartialItems.length > 0 && (
                    <div className="mt-1 text-xs text-slate-600">
                      {mergedPartialItems.map((x) => `${x.size}: ${x.quantity}`).join(" | ")}
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-md border border-[#ecebe3] px-3 py-2 text-sm text-slate-500">{t("page.packaging.noPartial")}</div>
              )
            ) : packingPreview.partialPackages.length === 0 ? (
              <div className="rounded-md border border-[#ecebe3] px-3 py-2 text-sm text-slate-500">{t("page.packaging.noPartial")}</div>
            ) : (
              packingPreview.partialPackages.map((p) => (
                <div key={p.index} className="rounded-md border border-[#ecebe3] px-3 py-2">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-sm font-medium">
                      {t("page.packaging.packageN", { n: p.index })} - {p.total}/{packingPreview.packageTotal}
                    </div>
                    <span className="badge">{packOnlyFullPackages ? t("page.packaging.pendingNotCreated") : t("page.packaging.willBeCreated")}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-600">
                    {p.items.length
                      ? p.items.map((x) => `${x.size}: ${x.qty}`).join(" | ")
                      : t("page.packaging.emptyExtra")}
                  </div>
                </div>
              ))
            )}
          </div>

          {packageWeightCount > 0 && (
            <div className="mt-4 border-t border-[#ecebe3] pt-4">
              <div className="mb-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h4 className="text-sm font-medium">{t("page.packaging.packageWeights")}</h4>
                  <div className="text-xs text-slate-500">{t("page.packaging.packageWeightsHint")}</div>
                </div>
                <button
                  type="button"
                  className="btn shrink-0"
                  onClick={() => setPackageWeights(Array.from({ length: packageWeightCount }, () => weightKg))}
                >
                  {t("page.packaging.applyWeightToAll")}
                </button>
              </div>
              <div className="grid max-h-[420px] grid-cols-1 gap-2 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3">
                {packagePlans.map((plan, index) => {
                  const qty = plan.items.reduce((sum, item) => sum + Number(item.quantity || 0), 0);
                  return (
                    <label key={index} className="block text-xs font-medium text-slate-500">
                      {t("page.packaging.packageWeightN", { n: index + 1 })} ({qty})
                      <input
                        className="input mt-1"
                        min={0}
                        step="0.001"
                        type="number"
                        value={packageWeights[index] || ""}
                        onChange={(e) => setPackageWeights((prev) => prev.map((value, i) => (i === index ? e.target.value : value)))}
                      />
                    </label>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>

      <PendingPackageWorkflow path="/api/packages/record-damage" resultKind="damage" onResolved={refreshPackagingOutputs} />
      <PackageQrSection
        key={`${po?.id || "none"}-${packageQrRefreshKey}`}
        productionOrderId={po?.id}
        onChanged={async () => {
          const sizePath = `/api/packages/first-grade/size-entry/${po?.id}`;
          await Promise.all([
            mutateBatchProgress(), mutatePackageSources(), mutateWo(), mutatePo(),
            mutateCache((key) => typeof key === "string" && (key === sizePath || key.startsWith(`${sizePath}?`))),
          ]);
          setCopiesTouched(false);
          setPkg(null);
          setPkgNotice(null);
        }}
      />

      {pkg && (
        <div className="card mt-6 p-4">
          <h3 className="font-medium">{t("page.packaging.created", { no: pkg.package_no })}</h3>
          {pkg.barcode !== "bulk" && (
            <>
              <p className="text-sm text-slate-500">{t("field.barcode")}: <code>{pkg.barcode}</code></p>
              <button type="button" className="btn btn-primary mt-2" onClick={() => api.openLabel(`/api/packages/${pkg.id}/label`)}>{t("btn.printLabel")}</button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
