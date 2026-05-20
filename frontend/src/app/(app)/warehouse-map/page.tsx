"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Bookmark, Clock3, MoveHorizontal, QrCode } from "lucide-react";
import { useRouter } from "next/navigation";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type CellStatus =
  | "free"
  | "partial"
  | "full"
  | "reserved"
  | "quarantine"
  | "receiving"
  | "unavailable";

type StorageMapCell = {
  code: string;
  zone: string;
  count?: number;
  status?: CellStatus | "free" | "partial" | "full";
  matched_count?: number;
};

type StoragePlacement = {
  id: number;
  package_no: string;
  barcode?: string | null;
  model_id?: number | null;
  model_code?: string | null;
  model_name?: string | null;
  color?: string | null;
  total_quantity: number;
  status: string;
  storage_cell: string;
  storage_shelf?: string | null;
  storage_placed_at?: string | null;
  matched?: boolean;
};

const ZONES: Array<{ id: string; cols: number; rows: number; labelKey: string }> = [
  { id: "N", cols: 16, rows: 1, labelKey: "warehouse.zone.unloading" },
  { id: "A", cols: 2, rows: 6, labelKey: "warehouse.zone.women" },
  { id: "B", cols: 2, rows: 6, labelKey: "warehouse.zone.women" },
  { id: "C", cols: 2, rows: 8, labelKey: "warehouse.zone.men" },
  { id: "D", cols: 2, rows: 10, labelKey: "warehouse.zone.new" },
  { id: "E", cols: 2, rows: 10, labelKey: "warehouse.zone.kids" },
  { id: "F", cols: 2, rows: 10, labelKey: "warehouse.zone.new" },
  { id: "G", cols: 2, rows: 8, labelKey: "warehouse.zone.men" },
  { id: "H", cols: 2, rows: 10, labelKey: "warehouse.zone.shipping" },
  { id: "M", cols: 1, rows: 12, labelKey: "warehouse.zone.mezzanine" },
  { id: "K", cols: 2, rows: 1, labelKey: "warehouse.zone.quarantine" },
  { id: "L", cols: 5, rows: 1, labelKey: "warehouse.zone.receiving" },
];

const STATUS_STYLE: Record<CellStatus, { dot: string; cellClass: string; pillClass: string }> = {
  free: {
    dot: "#4a8d5a",
    cellClass: "bg-[#e6efe2] border-[#cfe1c7] text-[#2f6b3e]",
    pillClass: "bg-[#e6efe2] border-[#cfe1c7] text-[#2f6b3e]",
  },
  partial: {
    dot: "#c19a2a",
    cellClass: "bg-[#f5ecc8] border-[#e6d6a3] text-[#8a6608]",
    pillClass: "bg-[#f5ecc8] border-[#e6d6a3] text-[#8a6608]",
  },
  full: {
    dot: "#cb6963",
    cellClass: "bg-[#f4d4d0] border-[#ebbab5] text-[#a3403e]",
    pillClass: "bg-[#f4d4d0] border-[#ebbab5] text-[#a3403e]",
  },
  reserved: {
    dot: "#6080b0",
    cellClass: "bg-[#dde6f3] border-[#c7d3ea] text-[#2a4c8a]",
    pillClass: "bg-[#dde6f3] border-[#c7d3ea] text-[#2a4c8a]",
  },
  quarantine: {
    dot: "#8b6cae",
    cellClass: "bg-[#e8dbf0] border-[#d9c8e5] text-[#5e3b85]",
    pillClass: "bg-[#e8dbf0] border-[#d9c8e5] text-[#5e3b85]",
  },
  receiving: {
    dot: "#c2410c",
    cellClass: "bg-[#fbe9dd] border-[#f1d4be] text-[#9a3308]",
    pillClass: "bg-[#fbe9dd] border-[#f1d4be] text-[#9a3308]",
  },
  unavailable: {
    dot: "#a8a395",
    cellClass: "bg-[#ecebe3] border-[#dfdcce] text-[#8a8472]",
    pillClass: "bg-[#ecebe3] border-[#dfdcce] text-[#8a8472]",
  },
};

function buildDefaultCells(): StorageMapCell[] {
  const rows: StorageMapCell[] = [];
  for (const z of ZONES) {
    const total = z.cols * z.rows;
    for (let idx = 1; idx <= total; idx++) {
      rows.push({
        code: `${z.id}-${String(idx).padStart(2, "0")}`,
        zone: z.id,
        count: 0,
        status: "free",
        matched_count: 0,
      });
    }
  }
  return rows;
}

function getCellStatus(cell: StorageMapCell): CellStatus {
  if (cell.zone === "K") return "quarantine";
  if (cell.zone === "L") return "receiving";
  if (cell.zone === "M") return "unavailable";
  if (cell.zone === "H" && (cell.count || 0) > 0 && cell.status !== "full") return "reserved";
  if (cell.status === "partial" || cell.status === "full" || cell.status === "free") return cell.status;
  return "free";
}

function normalizeShelf(shelf?: string | null): "S1" | "S2" {
  return shelf === "S2" ? "S2" : "S1";
}

function colorToHex(color?: string | null) {
  if (!color) return "#a8a395";
  const value = color.toLowerCase();
  if (value.includes("mint") || value.includes("мят")) return "#8fcdb3";
  if (value.includes("navy") || value.includes("син")) return "#5b6b96";
  if (value.includes("black") || value.includes("чер")) return "#45423a";
  if (value.includes("white") || value.includes("бел")) return "#e6e1d5";
  if (value.includes("rose") || value.includes("роз")) return "#d89cae";
  if (value.includes("beige") || value.includes("беж")) return "#ccb796";
  if (value.includes("grey") || value.includes("сер")) return "#9f9fa7";
  if (value.includes("blue") || value.includes("гол")) return "#8ab1d7";
  if (value.includes("olive") || value.includes("олив")) return "#94905e";
  return "#b6b09e";
}

function formatDateTime(value?: string | null, langCode?: string) {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  const localeMap: Record<string, string> = { en: "en-US", ru: "ru-RU", uz: "uz-UZ" };
  return d.toLocaleDateString(localeMap[langCode || "en"] || "en-US");
}

export default function WarehouseMapPage() {
  const router = useRouter();
  const { t, lang } = useT();
  const [modelQuery, setModelQuery] = useState("");
  const [selectedCell, setSelectedCell] = useState<string | null>(null);
  const [selectedShelf, setSelectedShelf] = useState<"S1" | "S2">("S1");
  const [message, setMessage] = useState("");
  const [messageError, setMessageError] = useState("");
  const [busyAction, setBusyAction] = useState<"move" | "label" | null>(null);
  const [bookmarkedPackages, setBookmarkedPackages] = useState<number[]>([]);
  const [moveSource, setMoveSource] = useState<StoragePlacement | null>(null);
  const [allowMixedModels, setAllowMixedModels] = useState(false);

  const mapQueryPath = modelQuery.trim()
    ? `/api/packages/storage-map?model_query=${encodeURIComponent(modelQuery.trim())}`
    : "/api/packages/storage-map";
  const { data: mapData, mutate: mutateMap } = useSWR<any>(mapQueryPath, fetcher);

  const normalizedCells = useMemo(() => {
    const source = (mapData?.cells || []) as StorageMapCell[];
    const rows = source.length ? source : buildDefaultCells();
    return rows.map((c) => ({
      ...c,
      count: c.count || 0,
      matched_count: c.matched_count || 0,
      status: getCellStatus(c),
    }));
  }, [mapData?.cells]);

  const placements = useMemo(() => (mapData?.placements || []) as StoragePlacement[], [mapData?.placements]);

  useEffect(() => {
    if (selectedCell) return;
    if (!normalizedCells.length) return;
    const firstOccupied = normalizedCells.find((c) => (c.count || 0) > 0);
    setSelectedCell((firstOccupied || normalizedCells[0]).code);
  }, [selectedCell, normalizedCells]);

  const cellsByCode = useMemo(() => {
    const map = new Map<string, StorageMapCell>();
    for (const c of normalizedCells) map.set(c.code, c);
    return map;
  }, [normalizedCells]);

  const placementsByCellShelf = useMemo(() => {
    const map = new Map<string, StoragePlacement[]>();
    for (const row of placements) {
      const key = `${row.storage_cell}|${normalizeShelf(row.storage_shelf)}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(row);
    }
    return map;
  }, [placements]);

  const selectedCellData = selectedCell ? cellsByCode.get(selectedCell) || null : null;
  const selectedZone = selectedCellData?.zone || "A";

  const selectedCellPlacements = useMemo(
    () => placements.filter((row) => row.storage_cell === selectedCell),
    [placements, selectedCell],
  );

  const selectedShelfPlacements = useMemo(
    () => selectedCellPlacements.filter((row) => normalizeShelf(row.storage_shelf) === selectedShelf),
    [selectedCellPlacements, selectedShelf],
  );

  const selectedPlacement = selectedShelfPlacements[0] || selectedCellPlacements[0] || null;
  const selectedCellQty = selectedCellPlacements.reduce((sum, row) => sum + (row.total_quantity || 0), 0);

  const zoneCells = useMemo(() => normalizedCells.filter((row) => row.zone === selectedZone), [normalizedCells, selectedZone]);
  const zoneTotal = zoneCells.length || 1;
  const zoneOccupied = zoneCells.filter((row) => (row.count || 0) > 0).length;
  const zoneFree = zoneTotal - zoneOccupied;
  const zoneFillPct = Math.round((zoneOccupied / zoneTotal) * 100);

  const zonePlacements = useMemo(
    () => placements.filter((row) => row.storage_cell?.startsWith(`${selectedZone}-`)),
    [placements, selectedZone],
  );

  const zoneSkuCount = useMemo(() => {
    const keys = new Set<string>();
    for (const row of zonePlacements) {
      keys.add(String(row.model_code || row.model_id || ""));
    }
    keys.delete("");
    return keys.size;
  }, [zonePlacements]);

  const zoneMovesToday = useMemo(() => {
    const now = new Date();
    return zonePlacements.filter((row) => {
      if (!row.storage_placed_at) return false;
      const dt = new Date(row.storage_placed_at);
      return (
        dt.getFullYear() === now.getFullYear() &&
        dt.getMonth() === now.getMonth() &&
        dt.getDate() === now.getDate()
      );
    }).length;
  }, [zonePlacements]);

  const zoneCodes = useMemo(() => {
    const rows = zoneCells
      .map((c) => c.code)
      .sort((a, b) => Number(a.split("-")[1]) - Number(b.split("-")[1]));
    return rows;
  }, [zoneCells]);

  const rackGroups = useMemo(() => {
    if (zoneCodes.length <= 5) return [zoneCodes];
    const half = Math.ceil(zoneCodes.length / 2);
    return [zoneCodes.slice(0, half), zoneCodes.slice(half)];
  }, [zoneCodes]);

  const totals = useMemo(() => {
    const totalQty = placements.reduce((sum, row) => sum + (row.total_quantity || 0), 0);
    const freeCells = (mapData?.summary?.cells_total || normalizedCells.length) - (mapData?.summary?.cells_occupied || 0);
    const reservedQty = placements
      .filter((row) => row.status === "reserved")
      .reduce((sum, row) => sum + (row.total_quantity || 0), 0);
    const receivingQty = placements
      .filter((row) => row.status === "packed")
      .reduce((sum, row) => sum + (row.total_quantity || 0), 0);
    return {
      totalQty,
      freeCells,
      occupiedCells: mapData?.summary?.cells_occupied || 0,
      reservedQty,
      receivingQty,
    };
  }, [placements, mapData?.summary, normalizedCells.length]);

  const selectedPlacementBookmarked = !!(selectedPlacement && bookmarkedPackages.includes(selectedPlacement.id));

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = localStorage.getItem("warehouse_map_bookmarks");
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) setBookmarkedPackages(parsed.filter((v) => Number.isInteger(v)));
    } catch {
      // ignore malformed local storage
    }
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const raw = localStorage.getItem("warehouse_map_allow_mixed_models");
      if (raw === "1") setAllowMixedModels(true);
    } catch {
      // ignore malformed local storage
    }
  }, []);

  function saveBookmarks(next: number[]) {
    setBookmarkedPackages(next);
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem("warehouse_map_bookmarks", JSON.stringify(next));
    } catch {
      // ignore local storage write failures
    }
  }

  function clearMessages() {
    setMessage("");
    setMessageError("");
  }

  function toggleAllowMixedModels(enabled: boolean) {
    setAllowMixedModels(enabled);
    if (typeof window === "undefined") return;
    try {
      localStorage.setItem("warehouse_map_allow_mixed_models", enabled ? "1" : "0");
    } catch {
      // ignore local storage write failures
    }
  }

  function toggleBookmark() {
    clearMessages();
    if (!selectedPlacement) {
      setMessageError(t("page.warehouseMap.noPackageSelected"));
      return;
    }
    const already = bookmarkedPackages.includes(selectedPlacement.id);
    const next = already
      ? bookmarkedPackages.filter((id) => id !== selectedPlacement.id)
      : [...bookmarkedPackages, selectedPlacement.id];
    saveBookmarks(next);
    setMessage(already ? t("page.warehouseMap.bookmarkRemoved") : t("page.warehouseMap.bookmarkAdded"));
  }

  async function handleMove() {
    clearMessages();
    if (!selectedCell) {
      setMessageError(t("page.warehouseMap.selectCellFirst"));
      return;
    }

    if (!moveSource) {
      if (!selectedPlacement) {
        setMessageError(t("page.warehouseMap.noPackageSelected"));
        return;
      }
      setMoveSource(selectedPlacement);
      setMessage(
        t("page.warehouseMap.moveArmed", {
          package: selectedPlacement.package_no,
          cell: selectedPlacement.storage_cell,
          shelf: normalizeShelf(selectedPlacement.storage_shelf),
        }),
      );
      return;
    }

    const sourceShelf = normalizeShelf(moveSource.storage_shelf);
    if (moveSource.storage_cell === selectedCell && sourceShelf === selectedShelf) {
      setMessageError(t("page.warehouseMap.moveSameTarget"));
      return;
    }

    const sourceModel = String(moveSource.model_code || moveSource.model_id || "");
    const targetPlacements = placements.filter((row) => row.storage_cell === selectedCell && row.id !== moveSource.id);
    const targetHasDifferentModel = targetPlacements.some((row) => {
      const targetModel = String(row.model_code || row.model_id || "");
      if (!targetModel || !sourceModel) return false;
      return targetModel !== sourceModel;
    });
    if (!allowMixedModels && targetHasDifferentModel) {
      setMessageError(t("page.warehouseMap.mixedModelBlocked"));
      return;
    }

    try {
      setBusyAction("move");
      await api.post(`/api/packages/${moveSource.id}/place-on-map`, {
        storage_cell: selectedCell,
        storage_shelf: selectedShelf,
      });
      await mutateMap();
      setMessage(
        t("page.warehouseMap.moveSuccess", {
          package: moveSource.package_no,
          cell: selectedCell,
          shelf: selectedShelf,
        }),
      );
      setMoveSource(null);
    } catch (err: any) {
      setMessageError(err?.message || t("page.warehouseMap.actionFailed"));
    } finally {
      setBusyAction(null);
    }
  }

  function cancelMove() {
    setMoveSource(null);
    clearMessages();
    setMessage(t("page.warehouseMap.moveCancelled"));
  }

  function openHistory() {
    clearMessages();
    if (!selectedPlacement) {
      setMessageError(t("page.warehouseMap.noPackageSelected"));
      return;
    }
    router.push(`/packages/${selectedPlacement.id}`);
  }

  async function openLabel() {
    clearMessages();
    if (!selectedPlacement) {
      setMessageError(t("page.warehouseMap.noPackageSelected"));
      return;
    }
    try {
      setBusyAction("label");
      await api.openLabel(`/api/packages/${selectedPlacement.id}/label`);
    } catch (err: any) {
      setMessageError(err?.message || t("page.warehouseMap.actionFailed"));
    } finally {
      setBusyAction(null);
    }
  }

  function renderCellButton(code: string) {
    const cell = cellsByCode.get(code) || { code, zone: code.split("-")[0], count: 0, matched_count: 0, status: "free" as CellStatus };
    const status = (cell.status as CellStatus) || "free";
    const style = STATUS_STYLE[status];
    const active = selectedCell === code;
    const hasMatch = (cell.matched_count || 0) > 0;

    return (
      <button
        key={code}
        type="button"
        onClick={() => {
          setSelectedCell(code);
          setSelectedShelf("S1");
        }}
        className={[
          "relative rounded-md border px-1.5 py-1 text-[10px] font-semibold transition",
          style.cellClass,
          "hover:-translate-y-px hover:shadow-sm",
          active ? "ring-2 ring-[#14110b] ring-offset-1" : "",
          hasMatch ? "shadow-[inset_0_0_0_1px_#c2410c]" : "",
        ].join(" ")}
      >
        {code}
      </button>
    );
  }

  function renderZone(id: string) {
    const zone = ZONES.find((z) => z.id === id);
    if (!zone) return null;
    const total = zone.cols * zone.rows;
    const codes = Array.from({ length: total }, (_, idx) => `${id}-${String(idx + 1).padStart(2, "0")}`);

    return (
      <div key={id} className="flex flex-col gap-1.5">
        <div className="flex items-baseline gap-1.5 px-0.5">
          <span className="text-[15px] font-bold tracking-tight text-[#14110b]">{id}</span>
          <span className="text-[9px] uppercase tracking-[0.1em] text-[#8a8472]">{t(zone.labelKey)}</span>
        </div>
        <div className="grid gap-[3px]" style={{ gridTemplateColumns: `repeat(${zone.cols}, minmax(0, 1fr))` }}>
          {codes.map((code) => renderCellButton(code))}
        </div>
      </div>
    );
  }

  function renderZoneStrip(id: string) {
    const zone = ZONES.find((z) => z.id === id);
    if (!zone) return null;
    const total = zone.cols * zone.rows;
    const codes = Array.from({ length: total }, (_, idx) => `${id}-${String(idx + 1).padStart(2, "0")}`);
    return (
      <div className="flex items-center gap-2">
        <div className="flex items-baseline gap-1.5 w-14 shrink-0">
          <span className="text-[15px] font-bold tracking-tight text-[#14110b]">{id}</span>
        </div>
        <div className="grid flex-1 gap-[3px]" style={{ gridTemplateColumns: `repeat(${zone.cols}, minmax(0, 1fr))` }}>
          {codes.map((code) => renderCellButton(code))}
        </div>
        <div className="w-20 shrink-0 text-right text-[9px] uppercase tracking-[0.1em] text-[#8a8472]">{t(zone.labelKey)}</div>
      </div>
    );
  }

  function slotCard(code: string, shelf: "S1" | "S2") {
    const key = `${code}|${shelf}`;
    const rows = placementsByCellShelf.get(key) || [];
    const top = rows[0];
    const active = selectedCell === code && selectedShelf === shelf;

    if (!top) {
      return (
        <button
          key={key}
          type="button"
          onClick={() => {
            setSelectedCell(code);
            setSelectedShelf(shelf);
          }}
          className={[
            "min-h-[88px] rounded-md border border-dashed px-2 py-2 text-[10px] uppercase tracking-wide transition",
            "flex items-center justify-center",
            active
              ? "border-[#c2410c] bg-[#fbe9dd] text-[#9a3308] ring-1 ring-[#c2410c]/40"
              : "border-[#ded9ca] bg-[#f8f6ef]/40 text-[#a8a395] hover:border-[#d1caba] hover:bg-[#fdf3eb]",
          ].join(" ")}
        >
          {t("page.warehouseMap.empty")}
        </button>
      );
    }

    return (
      <button
        key={key}
        type="button"
        onClick={() => {
          setSelectedCell(code);
          setSelectedShelf(shelf);
        }}
        className={[
          "min-h-[88px] rounded-md border px-2 py-2 text-left transition",
          "flex flex-col gap-0.5",
          active
            ? "border-[#c2410c] bg-[#fbe9dd] shadow-[0_4px_12px_rgba(194,65,12,0.12)] ring-1 ring-[#c2410c]/40"
            : "border-[#e3dfd3] bg-[#fdfcf8] hover:border-[#d1caba] hover:bg-[#fdf3eb]",
        ].join(" ")}
      >
        <div className="mono text-[11px] font-bold leading-tight text-[#14110b]">{top.model_code || top.model_id}</div>
        <div className="text-[10px] leading-tight text-[#56503f]">{top.model_name || top.package_no}</div>
        <div className="mt-auto flex items-center gap-1 text-[9px] leading-tight text-[#8a8472]">
          <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: colorToHex(top.color) }} />
          <span>{top.color || "-"}</span>
        </div>
        <div className="mono text-[10px] font-semibold text-[#c2410c]">
          {top.total_quantity} {t("field.qty")}
        </div>
      </button>
    );
  }

  function renderRackGroup(codes: string[], idx: number) {
    return (
      <div key={`rack-${idx}`} className="flex flex-col gap-1.5">
        <div className="grid gap-1.5" style={{ gridTemplateColumns: `32px repeat(${codes.length}, minmax(0, 1fr))` }}>
          <div />
          {codes.map((code) => (
            <div
              key={`${code}-head`}
              className={[
                "mono border-b pb-1 text-center text-[10px] tracking-wide",
                selectedCell === code ? "border-[#c2410c] font-bold text-[#c2410c]" : "border-[#ecebe3] text-[#8a8472]",
              ].join(" ")}
            >
              {code}
            </div>
          ))}
        </div>

        <div className="grid items-stretch gap-1.5" style={{ gridTemplateColumns: `32px repeat(${codes.length}, minmax(0, 1fr))` }}>
          <div className={`flex items-center justify-center text-[11px] font-semibold ${selectedShelf === "S1" ? "text-[#c2410c]" : "text-[#56503f]"}`}>S1</div>
          {codes.map((code) => slotCard(code, "S1"))}
        </div>

        <div className="grid items-stretch gap-1.5" style={{ gridTemplateColumns: `32px repeat(${codes.length}, minmax(0, 1fr))` }}>
          <div className={`flex items-center justify-center text-[11px] font-semibold ${selectedShelf === "S2" ? "text-[#c2410c]" : "text-[#56503f]"}`}>S2</div>
          {codes.map((code) => slotCard(code, "S2"))}
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader title={t("page.warehouseMap.title")} subtitle={t("page.warehouseMap.subtitle")} />

      <div className="mb-6 grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="kpi-card xl:col-span-1">
          <div className="label">{t("page.warehouseMap.kpiTotalOnHand")}</div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <div className="mono text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.totalQty.toLocaleString()}</div>
            <div className="text-sm text-[#8a8472]">{t("field.qty")}</div>
          </div>
        </div>
        <div className="kpi-card xl:col-span-1">
          <div className="label">{t("page.warehouseMap.kpiFreeCells")}</div>
          <div className="mt-1 mono text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.freeCells}</div>
          <div className="mt-2 text-[11px] text-[#8a8472]">
            {t("page.packageScan.occupiedCells", { occupied: totals.occupiedCells, total: mapData?.summary?.cells_total || normalizedCells.length })}
          </div>
        </div>
        <div className="kpi-card xl:col-span-1">
          <div className="label">{t("page.warehouseMap.kpiOccupiedCells")}</div>
          <div className="mt-1 mono text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.occupiedCells}</div>
        </div>
        <div className="kpi-card xl:col-span-1">
          <div className="label">{t("page.warehouseMap.kpiReserved")}</div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <div className="mono text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.reservedQty.toLocaleString()}</div>
            <div className="text-sm text-[#8a8472]">{t("field.qty")}</div>
          </div>
        </div>
        <div className="kpi-card xl:col-span-1">
          <div className="label">{t("page.warehouseMap.kpiReceiving")}</div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <div className="mono text-[28px] font-semibold leading-none tracking-tight text-[#14110b]">{totals.receivingQty.toLocaleString()}</div>
            <div className="text-sm text-[#8a8472]">{t("field.qty")}</div>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="card p-5">
          <div className="mb-3 flex flex-wrap items-end gap-2">
            <div className="flex-1">
              <label className="label">{t("page.shipments.findByModelPackage")}</label>
              <input
                className="input"
                placeholder={t("ph.modelPackageBarcodeSearch")}
                value={modelQuery}
                onChange={(e) => setModelQuery(e.target.value)}
              />
            </div>
            {selectedCell && (
              <button className="btn" onClick={() => setSelectedCell(null)}>
                {t("btn.clearCell")}
              </button>
            )}
          </div>

          <div className="mb-4 flex items-end justify-between gap-3">
            <div>
              <div className="app-card-title">{t("page.warehouseMap.mapCardTitle")}</div>
              <div className="mt-0.5 text-xs text-[#8a8472]">
                {t("page.warehouseMap.mapCardMeta", { cells: normalizedCells.length, zones: ZONES.length })}
              </div>
            </div>
            <div className="flex max-w-md flex-wrap justify-end gap-x-3 gap-y-1.5">
              {(["free", "partial", "full", "reserved", "quarantine", "receiving", "unavailable"] as CellStatus[]).map((status) => (
                <span key={status} className="inline-flex items-center gap-1 text-[10px] text-[#56503f]">
                  <span className="h-2 w-2 rounded-[2px]" style={{ background: STATUS_STYLE[status].dot }} />
                  {t(`page.warehouseMap.legend.${status}`)}
                </span>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <div className="min-w-[920px] space-y-4">
              <div>{renderZoneStrip("N")}</div>

              <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(8, minmax(0, 1fr)) minmax(0, 0.5fr)" }}>
                {["A", "B", "C", "D", "E", "F", "G", "H", "M"].map((id) => renderZone(id))}
              </div>

              <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(8, minmax(0, 1fr)) minmax(0, 0.5fr)" }}>
                <div style={{ gridColumn: "1 / 2" }}>{renderZone("K")}</div>
                <div style={{ gridColumn: "4 / 8" }}>{renderZone("L")}</div>
              </div>
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="card p-5">
            <div className="mb-3 flex items-center justify-between">
              <div className="label">
                {t("field.cell")} · {t("field.shelf")}
              </div>
              {selectedCellData && (
                <span
                  className={[
                    "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                    STATUS_STYLE[(selectedCellData.status as CellStatus) || "free"].pillClass,
                  ].join(" ")}
                >
                  <span className="h-1.5 w-1.5 rounded-full" style={{ background: STATUS_STYLE[(selectedCellData.status as CellStatus) || "free"].dot }} />
                  {t(`page.warehouseMap.legend.${(selectedCellData.status as CellStatus) || "free"}`)}
                </span>
              )}
            </div>

            <div className="flex items-baseline gap-3">
              <div className="mono text-[36px] font-semibold leading-none tracking-tight text-[#14110b]">{selectedCell || "-"}</div>
              <span className="mono inline-flex items-center rounded-md border border-[#c2410c] bg-[#fbe9dd] px-2 py-0.5 text-[12px] font-semibold text-[#9a3308]">
                {selectedShelf}
              </span>
            </div>
            <div className="mt-1 text-sm text-[#8a8472]">{selectedPlacement?.model_name || selectedPlacement?.package_no || t("page.warehouseMap.empty")}</div>
            {moveSource && (
              <div className="mt-2 rounded-md border border-[#f1d4be] bg-[#fbe9dd] px-2 py-1 text-xs text-[#9a3308]">
                {t("page.warehouseMap.movePending", {
                  package: moveSource.package_no,
                  cell: moveSource.storage_cell,
                  shelf: normalizeShelf(moveSource.storage_shelf),
                })}
              </div>
            )}

            <div className="mt-5 grid grid-cols-2 gap-3">
              <div>
                <div className="label">{t("field.model")}</div>
                <div className="mono text-sm font-medium text-[#14110b]">{selectedPlacement?.model_code || selectedPlacement?.model_id || "-"}</div>
              </div>
              <div>
                <div className="label">{t("field.color")}</div>
                <div className="flex items-center gap-1.5 text-sm font-medium text-[#14110b]">
                  {selectedPlacement?.color ? (
                    <>
                      <span className="h-3 w-3 rounded-full" style={{ background: colorToHex(selectedPlacement.color), border: "1px solid rgba(0,0,0,.12)" }} />
                      {selectedPlacement.color}
                    </>
                  ) : (
                    "-"
                  )}
                </div>
              </div>
              <div>
                <div className="label">{t("page.warehouseMap.onHand")}</div>
                <div className="mono text-sm font-medium text-[#14110b]">{selectedShelfPlacements.length}</div>
              </div>
              <div>
                <div className="label">{t("field.totalQty")}</div>
                <div className="mono text-sm font-medium text-[#14110b]">{selectedCellQty}</div>
              </div>
              <div>
                <div className="label">{t("field.packageNo")}</div>
                <div className="mono text-sm font-medium text-[#14110b]">{selectedPlacement?.package_no || "-"}</div>
              </div>
              <div>
                <div className="label">{t("page.warehouseMap.lastMove")}</div>
                <div className="mono text-sm font-medium text-[#14110b]">{formatDateTime(selectedPlacement?.storage_placed_at, lang)}</div>
              </div>
            </div>

            <div className="mt-5 flex gap-2">
              <button
                className="btn btn-accent flex-1 disabled:cursor-not-allowed disabled:opacity-60"
                onClick={handleMove}
                disabled={busyAction === "move" || busyAction === "label"}
              >
                <MoveHorizontal className="h-4 w-4" />
                {moveSource ? t("page.warehouseMap.confirmMove") : t("page.warehouseMap.move")}
              </button>
              <button
                className={`btn ${selectedPlacementBookmarked ? "border-[#c2410c] text-[#9a3308]" : ""}`}
                title="bookmark"
                onClick={toggleBookmark}
                disabled={busyAction === "move" || busyAction === "label"}
              >
                <Bookmark className="h-4 w-4" />
              </button>
              <button
                className="btn"
                title="history"
                onClick={openHistory}
                disabled={busyAction === "move" || busyAction === "label"}
              >
                <Clock3 className="h-4 w-4" />
              </button>
              <button
                className="btn disabled:cursor-not-allowed disabled:opacity-60"
                title="qr"
                onClick={openLabel}
                disabled={busyAction === "move" || busyAction === "label"}
              >
                <QrCode className="h-4 w-4" />
              </button>
              {moveSource && (
                <button className="btn" onClick={cancelMove} disabled={busyAction === "move"}>
                  {t("btn.cancel")}
                </button>
              )}
            </div>
            <label className="mt-3 flex items-center gap-2 text-xs text-[#56503f]">
              <input
                type="checkbox"
                className="h-4 w-4 accent-[#c2410c]"
                checked={allowMixedModels}
                onChange={(e) => toggleAllowMixedModels(e.target.checked)}
                disabled={busyAction === "move" || busyAction === "label"}
              />
              {t("page.warehouseMap.allowMultiModelsOneCell")}
            </label>
            {(message || messageError) && (
              <div className={`mt-2 text-xs ${messageError ? "text-red-700" : "text-[#1f7a4d]"}`}>
                {messageError || message}
              </div>
            )}
          </div>

          <div className="card p-5">
            <div className="mb-4">
              <div className="app-card-title">{t("page.warehouseMap.zoneActivity")}</div>
              <div className="mt-0.5 text-xs text-[#8a8472]">
                {t("page.warehouseMap.zonePrefix")} {selectedZone} · {t(ZONES.find((z) => z.id === selectedZone)?.labelKey || "warehouse.zone.unloading")}
              </div>
            </div>

            <div className="space-y-4">
              <div>
                <div className="mb-1.5 flex items-baseline justify-between">
                  <div className="label !mb-0">{t("page.warehouseMap.capacity")}</div>
                  <div className="mono text-sm font-semibold text-[#14110b]">{zoneFillPct}%</div>
                </div>
                <div className="mini-bar h-2">
                  <span style={{ width: `${zoneFillPct}%`, background: "linear-gradient(90deg, #c2410c, #1f7a4d 60%, #1e5fb3)" }} />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <div className="label">{t("page.warehouseMap.freePositions")}</div>
                  <div className="mono text-lg font-semibold text-[#14110b]">
                    {zoneFree}
                    <span className="text-xs text-[#8a8472]"> / {zoneTotal}</span>
                  </div>
                </div>
                <div>
                  <div className="label">{t("page.warehouseMap.skuOnRack")}</div>
                  <div className="mono text-lg font-semibold text-[#14110b]">{zoneSkuCount}</div>
                </div>
                <div>
                  <div className="label">{t("page.warehouseMap.movesToday")}</div>
                  <div className="mono text-lg font-semibold text-[#14110b]">{zoneMovesToday}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="card mt-6 p-5">
        <div className="mb-5">
          <div className="label">{t("page.warehouseMap.rackTitle")}</div>
          <div className="mono text-[24px] font-semibold tracking-tight text-[#14110b]">
            {selectedZone}-{selectedCell ? selectedCell.split("-")[1] : "01"}
          </div>
        </div>

        <div className="flex flex-col gap-6">
          {rackGroups.map((group, idx) => renderRackGroup(group, idx))}
        </div>
      </div>
    </div>
  );
}
