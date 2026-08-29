"use client";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { formatBatchLabel, formatBatchSerial } from "@/lib/batchSerial";
import PackageQrSection from "@/components/PackageQrSection";
import PageHeader from "@/components/PageHeader";
import { operationLabel, statusLabel } from "@/components/StagePipeline";
import WorkOrderProductInfo from "@/components/WorkOrderProductInfo";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { numberOrFallback, numberOrZero, parseNumberInput, type NumberInputValue } from "@/lib/numberInput";
import { orderReference } from "@/lib/orderRef";

type PackagePlanItem = { model_id: number; color: string; size: string; quantity: number };
type BatchAllocationPlan = { production_batch_id: number; quantity: number; label: string };
type PackagePlan = { items: PackagePlanItem[]; batch_allocations?: BatchAllocationPlan[] };
type PackagingRecordForm = {
  production_batch_id: number;
  input_qty: NumberInputValue;
  packed_qty: NumberInputValue;
  damaged_qty: NumberInputValue;
  packaging_material_used: string;
  notes: string;
};
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

function allocateDemandBySize(items: Array<{ size: string; planned_quantity: number }>, targetQty: number) {
  const target = Math.max(0, Math.floor(Number(targetQty || 0)));
  const total = items.reduce((s, it) => s + Math.max(0, Number(it.planned_quantity || 0)), 0);
  if (target <= 0 || total <= 0) {
    return items.map((it) => ({ ...it, planned_quantity: 0 }));
  }
  if (target === total) return items;

  const shares = items.map((it, index) => {
    const planned = Math.max(0, Number(it.planned_quantity || 0));
    const exact = (target * planned) / total;
    const base = Math.floor(exact);
    return { index, size: it.size, planned_quantity: base, remainder: exact - base };
  });
  let used = shares.reduce((s, it) => s + it.planned_quantity, 0);
  let left = target - used;
  const ranked = [...shares].sort((a, b) => b.remainder - a.remainder);
  let idx = 0;
  while (left > 0 && ranked.length > 0) {
    ranked[idx % ranked.length].planned_quantity += 1;
    left -= 1;
    idx += 1;
  }

  return shares
    .sort((a, b) => a.index - b.index)
    .map(({ size, planned_quantity }) => ({ size, planned_quantity }));
}

export default function PackagingPage() {
  const { t } = useT();
  const { me } = useMe();
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  const { data: wo, mutate: mutateWo } = useSWR<any>(`/api/work-orders/${id}`, fetcher);
  const { data: po, mutate: mutatePo } = useSWR<any>(wo ? `/api/production-orders/${wo.production_order_id}` : null, fetcher);
  const { data: batchProgress, mutate: mutateBatchProgress } = useSWR<any>(
    wo ? `/api/work-orders/${id}/packaging-batch-progress` : null,
    fetcher,
  );
  const { data: replacementStatus, mutate: mutateReplacementStatus } = useSWR<any>(
    wo ? `/api/work-orders/${id}/replacement-status` : null,
    fetcher,
  );
  const { data: so } = useSWR<any>(po?.sales_order_id ? `/api/sales-orders/${po.sales_order_id}` : null, fetcher);
  const { data: model } = useSWR<any>(po?.model_id ? `/api/models/${po.model_id}` : null, fetcher);
  const { data: customers = [] } = useSWR<any[]>("/api/customers", fetcher);
  const customerMap = useMemo(() => new Map(customers.map((c) => [c.id, c.name])), [customers]);

  const [rec, setRec] = useState<PackagingRecordForm>({
    production_batch_id: 0,
    input_qty: "",
    packed_qty: "",
    damaged_qty: "",
    packaging_material_used: "",
    notes: "",
  });
  const [pkgItems, setPkgItems] = useState<PackageRecipeItem[]>([{ size: "M", quantity: 60 }]);
  const [overrideCap, setOverrideCap] = useState(false);
  const [capacity, setCapacity] = useState<NumberInputValue>(60);
  const [weightKg, setWeightKg] = useState("");
  const [packageWeights, setPackageWeights] = useState<string[]>([]);
  const [color, setColor] = useState("white");
  const [copies, setCopies] = useState<NumberInputValue>(1);
  const [copiesTouched, setCopiesTouched] = useState(false);
  const [mergeAcrossBatches, setMergeAcrossBatches] = useState(false);
  const [packOnlyFullPackages, setPackOnlyFullPackages] = useState(false);
  const [recMsg, setRecMsg] = useState("");
  const [pkgNotice, setPkgNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [pkg, setPkg] = useState<any>(null);
  const [packageQrRefreshKey, setPackageQrRefreshKey] = useState(0);
  const canEditBreakdown = can(me, "*", "planning.production", "cutting.records", "packaging.records");
  const isAlreadyBatched = Array.isArray(po?.batches) && po.batches.length > 0;
  const batchItems = useMemo(() => (
    Array.isArray(batchProgress?.items) ? batchProgress.items : []
  ), [batchProgress?.items]);
  const selectedBatchProgress = useMemo(() => {
    const selectedId = Number(rec.production_batch_id || 0);
    return batchItems.find((row: any) => Number(row?.id || 0) === selectedId) || null;
  }, [batchItems, rec.production_batch_id]);

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

  const totalOrderColorQty = useMemo(
    () => orderColorItems.reduce((s: number, it: any) => s + Number(it?.planned_quantity || 0), 0),
    [orderColorItems],
  );
  const totalOrderQty = useMemo(
    () => (po?.items || []).reduce((s: number, it: any) => s + Math.max(0, Number(it?.planned_quantity || 0)), 0),
    [po?.items],
  );

  const packageableColorQty = useMemo(() => {
    if (isAlreadyBatched && selectedBatchProgress) {
      const hasPackageAccounting =
        Number(selectedBatchProgress.packed_qty || 0) > 0 || Number(selectedBatchProgress.packaged_qty || 0) > 0;
      if (hasPackageAccounting) {
        return Math.max(0, Number(selectedBatchProgress.available_to_package ?? selectedBatchProgress.packed_qty ?? 0));
      }
    }
    const packedQty = isAlreadyBatched
      ? selectedBatchProgress
        ? 0
        : Number(rec.packed_qty || 0)
      : Number(wo?.passed_qty || wo?.actual_output_qty || rec.packed_qty || 0);
    if (packedQty > 0) return packedQty;

    const stagePlannedQty = Math.max(
      0,
      Number(wo?.planned_output_qty || 0),
      Number(po?.planned_quantity || 0),
      totalOrderQty,
    );
    if (totalOrderQty > 0 && totalOrderColorQty > 0) {
      return Math.max(totalOrderColorQty, Math.round((stagePlannedQty * totalOrderColorQty) / totalOrderQty));
    }
    return Math.max(totalOrderColorQty, stagePlannedQty);
  }, [
    isAlreadyBatched,
    po?.planned_quantity,
    rec.packed_qty,
    selectedBatchProgress,
    totalOrderColorQty,
    totalOrderQty,
    wo?.actual_output_qty,
    wo?.passed_qty,
    wo?.planned_output_qty,
  ]);

  const colorOrderItems = useMemo(
    () => allocateDemandBySize(orderColorItems, packageableColorQty),
    [orderColorItems, packageableColorQty],
  );

  const totalColorQty = useMemo(
    () => colorOrderItems.reduce((s: number, it: any) => s + Number(it?.planned_quantity || 0), 0),
    [colorOrderItems],
  );

  const suggestedCopies = useMemo(() => {
    const cap = Math.max(1, Number(capacity || 0));
    return totalColorQty > 0 ? Math.max(1, Math.ceil(totalColorQty / cap)) : 1;
  }, [totalColorQty, capacity]);

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

    return out.map(({ size, quantity }) => ({ size, quantity }));
  }, [colorOrderItems, capacity]);

  const packingPreview = useMemo(() => {
    const perPackage = pkgItems
      .map((it) => ({ size: String(it.size || "").trim(), qty: Math.max(0, Number(it.quantity || 0)) }))
      .filter((it) => it.size && it.qty > 0);
    const perPackageMap = new Map<string, number>();
    for (const it of perPackage) perPackageMap.set(it.size, (perPackageMap.get(it.size) || 0) + it.qty);

    const demandMap = new Map<string, number>();
    for (const it of colorOrderItems) demandMap.set(String(it.size || ""), Math.max(0, Number(it.planned_quantity || 0)));

    const packageTotal = perPackage.reduce((s, it) => s + it.qty, 0);
    if (perPackage.length === 0 || packageTotal <= 0) {
      return { fullCount: 0, notFullCount: 0, packageTotal: 0, partialPackages: [] as Array<{ index: number; items: Array<{ size: string; qty: number }>; total: number }> };
    }

    let fullByRecipe = Number.POSITIVE_INFINITY;
    for (const it of perPackage) {
      const demand = demandMap.get(it.size) || 0;
      fullByRecipe = Math.min(fullByRecipe, Math.floor(demand / it.qty));
    }
    if (!Number.isFinite(fullByRecipe)) fullByRecipe = 0;

    const targetCopies = Math.max(1, Number(copies || 1));
    const fullCount = Math.max(0, Math.min(targetCopies, fullByRecipe));

    const remainingMap = new Map<string, number>();
    for (const [size, demand] of demandMap.entries()) {
      const used = (perPackageMap.get(size) || 0) * fullCount;
      remainingMap.set(size, Math.max(0, demand - used));
    }
    const remainingTotal = Array.from(remainingMap.values()).reduce((a, b) => a + b, 0);
    const partialFromDemand = remainingTotal > 0 ? Math.ceil(remainingTotal / packageTotal) : 0;
    const extraEmpty = Math.max(0, targetCopies - fullCount - partialFromDemand);

    const partialPackages: Array<{ index: number; items: Array<{ size: string; qty: number }>; total: number }> = [];
    for (let p = 0; p < partialFromDemand; p += 1) {
      let capLeft = packageTotal;
      const packItems: Array<{ size: string; qty: number }> = [];

      for (const it of perPackage) {
        if (capLeft <= 0) break;
        const rem = remainingMap.get(it.size) || 0;
        const take = Math.min(rem, it.qty, capLeft);
        if (take > 0) {
          packItems.push({ size: it.size, qty: take });
          remainingMap.set(it.size, rem - take);
          capLeft -= take;
        }
      }

      if (capLeft > 0) {
        let progress = true;
        while (capLeft > 0 && progress) {
          progress = false;
          for (const it of perPackage) {
            if (capLeft <= 0) break;
            const rem = remainingMap.get(it.size) || 0;
            if (rem > 0) {
              const idx = packItems.findIndex((x) => x.size === it.size);
              if (idx >= 0) packItems[idx].qty += 1;
              else packItems.push({ size: it.size, qty: 1 });
              remainingMap.set(it.size, rem - 1);
              capLeft -= 1;
              progress = true;
            }
          }
        }
      }

      const total = packItems.reduce((s, x) => s + x.qty, 0);
      partialPackages.push({ index: p + 1, items: packItems, total });
    }

    for (let i = 0; i < extraEmpty; i += 1) {
      partialPackages.push({ index: partialFromDemand + i + 1, items: [], total: 0 });
    }

    return {
      fullCount,
      notFullCount: partialPackages.length,
      packageTotal,
      partialPackages,
    };
  }, [pkgItems, colorOrderItems, copies]);

  const basePackageItems = useMemo<PackagePlanItem[]>(() => (
    pkgItems
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
    if (plans.length === 0 && basePackageItems.length > 0 && !packOnlyFullPackages) plans.push({ items: basePackageItems });
    return plans;
  }, [basePackageItems, color, packOnlyFullPackages, packingPreview.fullCount, packingPreview.partialPackages, po?.model_id]);

  const batchPackageAvailability = useMemo(() => (
    batchItems
      .map((row: any) => {
        const hasPackageAccounting = row?.available_to_package !== undefined || Number(row?.packaged_qty || 0) > 0;
        const available = hasPackageAccounting
          ? Math.max(0, Number(row?.available_to_package || 0))
          : Math.max(0, Number(row?.packed_qty || 0));
        return {
          id: Number(row?.id || 0),
          label: formatBatchLabel(row, po?.id),
          available,
        };
      })
      .filter((row: any) => row.id > 0 && row.available > 0)
  ), [batchItems, po?.id]);

  const mergedPackingPlan = useMemo(() => {
    const packageTotal = basePackageItems.reduce((s, i) => s + Math.max(0, Number(i.quantity || 0)), 0);
    const totalAvailable = batchPackageAvailability.reduce((s, b) => s + b.available, 0);
    if (!isAlreadyBatched || packageTotal <= 0 || basePackageItems.length === 0) {
      return {
        plans: [] as PackagePlan[],
        totalAvailable,
        pendingQty: totalAvailable,
        pendingAllocations: [] as BatchAllocationPlan[],
        crossBatchCount: 0,
        previewLines: [] as string[],
      };
    }

    const sources = batchPackageAvailability.map((b) => ({ ...b }));
    const fullCount = Math.floor(totalAvailable / packageTotal);
    const plans: PackagePlan[] = [];
    let sourceIndex = 0;

    for (let i = 0; i < fullCount; i += 1) {
      let left = packageTotal;
      const allocations: BatchAllocationPlan[] = [];
      while (left > 0 && sourceIndex < sources.length) {
        const source = sources[sourceIndex];
        const take = Math.min(left, source.available);
        if (take > 0) {
          allocations.push({ production_batch_id: source.id, quantity: take, label: source.label });
          source.available -= take;
          left -= take;
        }
        if (source.available <= 0) sourceIndex += 1;
      }
      if (left === 0) {
        plans.push({ items: basePackageItems, batch_allocations: allocations });
      }
    }

    const pendingSources = sources.slice(sourceIndex).filter((b) => Math.max(0, b.available) > 0);
    const pendingQty = pendingSources.reduce((s, b) => s + Math.max(0, b.available), 0);
    const pendingAllocations = pendingSources.map((source) => ({
      production_batch_id: source.id,
      quantity: Math.max(0, source.available),
      label: source.label,
    }));
    const crossBatchPlans = plans.filter((p) => (p.batch_allocations || []).length > 1);
    const previewLines = crossBatchPlans.slice(0, 3).map((p) => (
      (p.batch_allocations || []).map((a) => `${a.label}: ${a.quantity}`).join(" + ")
    ));
    return { plans, totalAvailable, pendingQty, pendingAllocations, crossBatchCount: crossBatchPlans.length, previewLines };
  }, [basePackageItems, batchPackageAvailability, isAlreadyBatched]);

  const mergedPartialItems = useMemo(
    () => trimPackageItemsToQuantity(basePackageItems, mergedPackingPlan.pendingQty),
    [basePackageItems, mergedPackingPlan.pendingQty],
  );

  const packagePlans = useMemo<PackagePlan[]>(() => {
    if (!mergeAcrossBatches) return standardPackagePlans;
    if (packOnlyFullPackages || mergedPackingPlan.pendingQty <= 0 || mergedPartialItems.length === 0) {
      return mergedPackingPlan.plans;
    }
    return [
      ...mergedPackingPlan.plans,
      {
        items: mergedPartialItems,
        batch_allocations: mergedPackingPlan.pendingAllocations,
      },
    ];
  }, [
    mergeAcrossBatches,
    mergedPackingPlan.pendingAllocations,
    mergedPackingPlan.pendingQty,
    mergedPackingPlan.plans,
    mergedPartialItems,
    packOnlyFullPackages,
    standardPackagePlans,
  ]);
  const packageWeightCount = packagePlans.length;

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
    if (!isAlreadyBatched || !Array.isArray(po?.batches) || po.batches.length === 0) return;
    setRec((prev) => {
      if (prev.production_batch_id) return prev;
      return { ...prev, production_batch_id: Number(po.batches[0].id || 0) };
    });
  }, [isAlreadyBatched, po?.batches]);

  async function refreshPackagingOutputs() {
    await Promise.all([mutateBatchProgress(), mutateWo(), mutatePo(), mutateReplacementStatus()]);
    setPackageQrRefreshKey((prev) => prev + 1);
  }

  async function saveBreakdown(items: Array<{ id?: number | null; color: string; size: string; planned_quantity: number }>) {
    if (!po?.id) return;
    await api.put(`/api/production-orders/${po.id}/breakdown`, { items });
    await refreshPackagingOutputs();
  }

  async function submitRec(e: React.FormEvent) {
    e.preventDefault();
    setRecMsg("");
    setPkgNotice(null);
    if (isAlreadyBatched && !rec.production_batch_id) {
      setRecMsg(t("batch.selectBeforeSaving", { operation: operationLabel("packaging", t).toLowerCase() }));
      return;
    }
    try {
      await api.post("/api/packaging/records", {
        work_order_id: id,
        ...rec,
        input_qty: numberOrZero(rec.input_qty),
        packed_qty: numberOrZero(rec.packed_qty),
        damaged_qty: numberOrZero(rec.damaged_qty),
        production_batch_id: rec.production_batch_id || null,
      });
      await refreshPackagingOutputs();
      setRecMsg(t("msg.saved"));
    } catch (e: any) {
      setRecMsg(e.message);
    }
  }

  async function createPkg(e: React.FormEvent) {
    e.preventDefault();
    setPkgNotice(null);
    setIsCreating(true);
    try {
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
        override_capacity: overrideCap,
        production_batch_id: mergeAcrossBatches ? null : rec.production_batch_id || null,
      };
      if (packagePlans.length === 0) {
        throw new Error("No package items to create.");
      }

      const createsPartialPackage = !packOnlyFullPackages && packingPreview.partialPackages.some((p) => p.total > 0);
      if (!mergeAcrossBatches && packagePlans.length > 1 && !createsPartialPackage) {
        const r = await api.post("/api/packages/bulk", {
          ...payloadBase,
          items: packagePlans[0].items,
          count: packagePlans.length,
          weight_kg_values: weightValues,
        });
        setPkg({ id: r.package_ids?.[0], package_no: r.package_nos?.[0], barcode: "bulk" });
        const createdCount = Number(r?.count || packagePlans.length || 0);
        const firstPackageNo = r?.package_nos?.[0];
        setPkgNotice({
          type: "success",
          text: firstPackageNo
            ? t("page.packaging.bulkCreatedWithFirst", { count: createdCount, no: firstPackageNo })
            : t("page.packaging.bulkCreated", { count: createdCount }),
        });
        await refreshPackagingOutputs();
        if (r.package_ids?.length) {
          await api.openLabel(`/api/packages/label-sheet/by-ids?ids=${r.package_ids.join(",")}`);
        }
      } else {
        const created = [];
        for (let index = 0; index < packagePlans.length; index += 1) {
          const plan = packagePlans[index];
          created.push(await api.post("/api/packages", {
            ...payloadBase,
            weight_kg: weightValues[index],
            items: plan.items,
            batch_allocations: plan.batch_allocations || [],
          }));
        }
        const r = created[0];
        setPkg(packagePlans.length > 1 ? { id: r?.id, package_no: r?.package_no, barcode: "bulk" } : r);
        setPkgNotice({
          type: "success",
          text: packagePlans.length > 1
            ? t("page.packaging.bulkCreatedWithFirst", { count: created.length, no: r?.package_no || "#" })
            : t("page.packaging.singleCreated", { no: r?.package_no || "#" }),
        });
        const ids = created.map((p) => p?.id).filter(Boolean);
        await refreshPackagingOutputs();
        if (ids.length > 1) {
          await api.openLabel(`/api/packages/label-sheet/by-ids?ids=${ids.join(",")}`);
        }
      }
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
      {Number(replacementStatus?.open_qty || 0) > 0 && (
        <div className="mb-4 border-y border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-950">
          <div className="font-semibold">
            {t("replacement.packagingOpen", { count: Number(replacementStatus.open_qty).toLocaleString() })}
          </div>
          <div className="mt-1 text-amber-900">{t("replacement.packagingHint")}</div>
        </div>
      )}
      <div className={`mb-4 grid gap-4 ${isAlreadyBatched ? "2xl:grid-cols-[360px_minmax(0,1fr)]" : "max-w-3xl"}`}>
        <form onSubmit={submitRec} className="card p-4">
          <div className="mb-3 text-base font-semibold">{t("btn.savePackagingRecord")}</div>
          <div className="grid grid-cols-2 gap-3">
            {isAlreadyBatched && (
              <div className="col-span-2">
                <label className="label">{t("batch.orderBatch")}</label>
                <select
                  className="input"
                  value={rec.production_batch_id}
                  onChange={(e) => {
                    setRec({ ...rec, production_batch_id: Number(e.target.value) });
                    setCopiesTouched(false);
                  }}
                >
                  <option value={0}>{t("batch.selectBatch")}</option>
                  {(po?.batches || []).map((b: any) => (
                    <option key={b.id} value={b.id}>
                      {formatBatchLabel(b, po?.id)} ({b.planned_quantity})
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <label className="label">{t("field.inputQty")}</label>
              <input className="input" type="number" value={rec.input_qty} onChange={(e) => setRec({ ...rec, input_qty: parseNumberInput(e.target.value) })} />
            </div>
            <div>
              <label className="label">{t("field.output")}</label>
              <input className="input" type="number" value={rec.packed_qty} onChange={(e) => setRec({ ...rec, packed_qty: parseNumberInput(e.target.value) })} />
            </div>
            <div>
              <label className="label">{t("field.damaged")}</label>
              <input className="input" type="number" value={rec.damaged_qty} onChange={(e) => setRec({ ...rec, damaged_qty: parseNumberInput(e.target.value) })} />
            </div>
            <div>
              <label className="label">{t("field.materialUsed")}</label>
              <input className="input" value={rec.packaging_material_used} onChange={(e) => setRec({ ...rec, packaging_material_used: e.target.value })} />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-3">
            <button className="btn btn-primary">{t("btn.savePackagingRecord")}</button>
            {recMsg && <div className="text-sm text-slate-600">{recMsg}</div>}
          </div>
        </form>

        {isAlreadyBatched && (
          <div className="card p-4">
            <div className="mb-2 text-base font-semibold">{t("batch.managedInsideWorkOrder")}</div>
            <div className="overflow-x-auto">
              <table className="table text-sm">
                <thead>
                  <tr>
                    <th>{t("field.batch")}</th>
                    <th>{t("statusValue.planned")}</th>
                    <th>{t("field.packed")}</th>
                    <th>{t("field.damaged")}</th>
                    <th>{t("replacement.waiting")}</th>
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
                      <td>{row.planned_quantity}</td>
                      <td>{row.packed_qty}</td>
                      <td>{row.damaged_qty}</td>
                      <td>{row.waiting_replacement_qty || 0}</td>
                      <td>{row.remaining_quantity}</td>
                      <td>{row.progress_pct}%</td>
                    </tr>
                  ))}
                  {batchItems.length === 0 && (
                    <tr>
                      <td colSpan={7} className="text-slate-500">{t("batch.noProgressYet")}</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <form onSubmit={createPkg} className="card space-y-3 p-6">
          <h3 className="font-medium">{t("page.packaging.newPackage")}</h3>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
            <div>
              <label className="label">{t("field.color")}</label>
              <input className="input" value={color} onChange={(e) => setColor(e.target.value)} />
            </div>
            <div>
              <label className="label">{t("field.capacity")}</label>
              <input className="input" type="number" value={capacity} onChange={(e) => setCapacity(parseNumberInput(e.target.value))} />
            </div>
            <div>
              <label className="label">{t("page.packaging.defaultWeightKg")}</label>
              <input
                className="input"
                min={0}
                step="0.001"
                type="number"
                value={weightKg}
                onChange={(e) => setWeightKg(e.target.value)}
              />
            </div>
            <label className="mb-2 flex items-end gap-2 text-sm">
              <input type="checkbox" checked={overrideCap} onChange={(e) => setOverrideCap(e.target.checked)} />
              {t("page.packaging.adminOverride")}
            </label>
            <div>
              <label className="label">{t("page.packaging.copies")}</label>
              <input
                className="input"
                min={1}
                type="number"
                value={copies}
                onChange={(e) => {
                  setCopiesTouched(true);
                  setCopies(parseNumberInput(e.target.value));
                }}
              />
            </div>
          </div>
          <div className="text-xs text-slate-500">
            {t("page.packaging.autoMixHint")}
          </div>
          <div className="rounded-md border border-[#ecebe3] bg-[#faf9f4] px-3 py-2 text-sm">
            <label className="flex items-start gap-2">
              <input
                className="mt-1"
                type="checkbox"
                checked={!packOnlyFullPackages}
                onChange={(e) => setPackOnlyFullPackages(!e.target.checked)}
              />
              <span>
                <span className="font-medium">{t("page.packaging.createPartialPackage")}</span>
                <span className="mt-1 block text-xs text-slate-500">{t("page.packaging.createPartialPackageHint")}</span>
              </span>
            </label>
            <label className="mt-3 flex items-start gap-2 border-t border-[#ecebe3] pt-3">
              <input
                className="mt-1"
                type="checkbox"
                checked={packOnlyFullPackages}
                onChange={(e) => setPackOnlyFullPackages(e.target.checked)}
              />
              <span>
                <span className="font-medium">{t("page.packaging.holdPartialPackage")}</span>
                <span className="mt-1 block text-xs text-slate-500">{t("page.packaging.packOnlyFullHint")}</span>
              </span>
            </label>
          </div>
          {isAlreadyBatched && (
            <div className="rounded-md border border-[#ecebe3] bg-[#faf9f4] px-3 py-2 text-sm">
              <label className="flex items-start gap-2">
                <input
                  className="mt-1"
                  type="checkbox"
                  checked={mergeAcrossBatches}
                  onChange={(e) => setMergeAcrossBatches(e.target.checked)}
                />
                <span>
                  <span className="font-medium">{t("page.packaging.mergeAcrossBatches")}</span>
                  <span className="mt-1 block text-xs text-slate-500">{t("page.packaging.mergeHint")}</span>
                </span>
              </label>
              <div className="mt-2 text-xs text-slate-600">
                {mergedPackingPlan.plans.length > 0
                  ? `${t("page.packaging.mergeFullPackages", { count: mergedPackingPlan.plans.length })} · ${t("page.packaging.mergePending", { count: mergedPackingPlan.pendingQty })}`
                  : t("page.packaging.mergeNoPacked")}
              </div>
              {mergedPackingPlan.previewLines.length > 0 && (
                <div className="mt-1 text-xs text-slate-600">
                  {t("page.packaging.mergeSources")}: {mergedPackingPlan.previewLines.join(" | ")}
                </div>
              )}
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

          <button className="btn btn-primary" disabled={isCreating || packagePlans.length === 0}>
            {isCreating ? t("common.creating") : packagePlans.length > 1 ? t("page.packaging.createCopies", { count: packagePlans.length }) : t("btn.createPackage")}
          </button>
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
        </form>

        <div className="card p-6">
          <h3 className="font-medium">{t("page.packaging.partialTitle")}</h3>
          <div className="mt-3 grid grid-cols-3 gap-3 text-sm">
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.packaging.fullPackages")}</div>
              <div className="text-xl font-semibold">{mergeAcrossBatches ? mergedPackingPlan.plans.length : packingPreview.fullCount}</div>
            </div>
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.packaging.notFullPackages")}</div>
              <div className="text-xl font-semibold">
                {mergeAcrossBatches ? (mergedPackingPlan.pendingQty > 0 ? 1 : 0) : packingPreview.notFullCount}
              </div>
            </div>
            <div className="rounded-md border border-[#ecebe3] p-3">
              <div className="text-xs uppercase tracking-wide text-slate-500">{t("page.packaging.packCapacity")}</div>
              <div className="text-xl font-semibold">{packingPreview.packageTotal}</div>
            </div>
          </div>
          <div className="mt-4 text-xs text-slate-500">
            {t("page.packaging.previewHint")}
          </div>
          <div className="mt-3 space-y-2">
            {mergeAcrossBatches ? (
              mergedPackingPlan.pendingQty > 0 ? (
                <div className="rounded-md border border-[#ecebe3] px-3 py-2">
                  <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-sm font-medium">
                      {packOnlyFullPackages ? t("page.packaging.pendingLeftover") : t("page.packaging.finalPartialPackage")} - {mergedPackingPlan.pendingQty}/{packingPreview.packageTotal}
                    </div>
                    <span className="badge">{packOnlyFullPackages ? t("page.packaging.pendingNotCreated") : t("page.packaging.willBeCreated")}</span>
                  </div>
                  <div className="mt-1 text-xs text-slate-600">
                    {packOnlyFullPackages ? t("page.packaging.pendingLeftoverHint") : t("page.packaging.partialWarehouseHint")}
                  </div>
                  {!packOnlyFullPackages && mergedPartialItems.length > 0 && (
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
                    <label key={index} className="block text-xs font-medium uppercase tracking-wide text-slate-500">
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

      <PackageQrSection
        key={`${po?.id || "none"}-${packageQrRefreshKey}`}
        productionOrderId={po?.id}
        onChanged={async () => {
          await Promise.all([mutateBatchProgress(), mutateWo()]);
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
