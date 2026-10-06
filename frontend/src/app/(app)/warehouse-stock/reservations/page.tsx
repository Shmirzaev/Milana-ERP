"use client";

import { useDeferredValue, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import useSWRInfinite from "swr/infinite";
import PageHeader from "@/components/PageHeader";
import SearchableSelect from "@/components/SearchableSelect";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { formatModelVariantCode } from "@/lib/variantDisplay";

type Pack = { id: number; package_no: string; model_code: string; model_name: string;
  quantity: number; customer_id?: number; customer_name?: string; notes?: string; reserved_at?: string };
type PackPage = { rows: Pack[]; total: number; has_more: boolean };

export default function WarehouseReservationsPage() {
  const { t } = useT();
  const { me } = useMe();
  const router = useRouter();
  const [reserved, setReserved] = useState(true);
  const [query, setQuery] = useState("");
  const search = useDeferredValue(query.trim());
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [customerSearch, setCustomerSearch] = useState("");
  const customerQuery = useDeferredValue(customerSearch.trim());
  const [notes, setNotes] = useState("");
  const [selected, setSelected] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const request = useRef<{ fingerprint: string; key: string } | null>(null);
  const customerUrl = `/api/warehouse-reservations/customers?q=${encodeURIComponent(customerQuery)}`;
  const { data: customers } = useSWR<{ rows: { id: number; name: string }[] }>(customerUrl, fetcher);
  const { data, error, isLoading, isValidating, setSize, mutate } = useSWRInfinite<PackPage>(
    (index, previous) => previous && !previous.has_more ? null
      : `/api/warehouse-reservations?reserved=${reserved}&page=${index + 1}&page_size=50&q=${encodeURIComponent(search)}${reserved && customerId ? `&customer_id=${customerId}` : ""}`, fetcher);
  const rows = data?.flatMap(page => page.rows) || [];
  const total = data?.[0]?.total || 0;
  useEffect(() => { setSelected([]); }, [reserved, search, customerId]);

  async function act(action: "reserve" | "release" | "prepare-shipment") {
    if (busy || !selected.length || (action === "reserve" && !customerId)) return;
    setBusy(true); setActionError("");
    const body = action === "reserve" ? { package_ids: selected, customer_id: customerId, notes: notes || null } : { package_ids: selected };
    const fingerprint = JSON.stringify({ action, body });
    if (request.current?.fingerprint !== fingerprint) request.current = { fingerprint, key: crypto.randomUUID() };
    try {
      const response = await api.postWithHeaders<{ id?: number }>(`/api/warehouse-reservations${action === "reserve" ? "" : `/${action}`}`,
        body, { "Idempotency-Key": request.current.key });
      request.current = null;
      setSelected([]);
      if (action === "prepare-shipment" && response.id) {
        router.push(`/shipments?shipment_id=${response.id}`);
      } else {
        await mutate();
      }
    } catch (e: any) { setActionError(e.message); }
    finally { setBusy(false); }
  }

  return <div>
    <PageHeader title={t("warehouseReservations.title")} subtitle={t("warehouseReservations.subtitle")} />
    <div className="mb-4 flex flex-wrap gap-2">
      <button className={reserved ? "btn btn-primary" : "btn"} onClick={() => setReserved(true)}>{t("warehouseReservations.reserved")}</button>
      <button className={!reserved ? "btn btn-primary" : "btn"} onClick={() => setReserved(false)}>{t("warehouseReservations.available")}</button>
    </div>
    <div className="mb-4 grid gap-3 md:grid-cols-2">
      <label><span className="label">{t("common.search")}</span><input type="search" className="input" value={query} maxLength={100} onChange={e => setQuery(e.target.value)} /></label>
      <div><label className="label" htmlFor="reservation-customer">{t("common.customer")}</label>
        <SearchableSelect inputId="reservation-customer" value={customerId} onChange={value => setCustomerId(Number(value) || null)}
          options={(customers?.rows || []).map(customer => ({ value: customer.id, label: customer.name }))}
          onSearchChange={setCustomerSearch} serverFilter placeholder={t("warehouseReservations.selectCustomer")}
          noResultsText={t("page.search.noMatches")} />
        {reserved && customerId && <button className="btn mt-1" onClick={() => setCustomerId(null)}>{t("common.clear")}</button>}
      </div>
      {!reserved && <label><span className="label">{t("field.notes")}</span><input className="input" value={notes} maxLength={1000} onChange={e => setNotes(e.target.value)} /></label>}
    </div>
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <span>{selected.length} / 50</span>
      {reserved ? <>
        <button className="btn" disabled={busy || !selected.length} onClick={() => void act("release")}>{t("warehouseReservations.release")}</button>
        {can(me, "storage.shipment", "*") && <button className="btn btn-primary" disabled={busy || !selected.length} onClick={() => void act("prepare-shipment")}>{t("warehouseReservations.prepareShipment")}</button>}
      </> : <button className="btn btn-primary" disabled={busy || !selected.length || !customerId} onClick={() => void act("reserve")}>{t("warehouseReservations.reserve")}</button>}
    </div>
    {(actionError || error) && <div role="alert" className="mb-3 text-sm text-red-700">{actionError || String(error.message)} {error && <button className="btn" onClick={() => void mutate()}>{t("common.retry")}</button>}</div>}
    <div className="card overflow-x-auto" aria-busy={busy || isLoading}>
      <table className="table"><thead><tr><th>{t("warehouseReservations.select")}</th><th>{t("field.package")}</th><th>{t("field.model")}</th><th>{t("field.qty")}</th>{reserved && <><th>{t("common.customer")}</th><th>{t("field.notes")}</th></>}</tr></thead>
        <tbody>{rows.map(row => <tr key={row.id}>
          <td><input type="checkbox" aria-label={row.package_no} checked={selected.includes(row.id)} disabled={busy || (!selected.includes(row.id) && selected.length >= 50)}
            onChange={e => setSelected(previous => e.target.checked ? [...previous, row.id] : previous.filter(id => id !== row.id))} /></td>
          <td>{row.package_no}</td><td>{formatModelVariantCode(row.model_code)} · {row.model_name}</td><td>{row.quantity}</td>
          {reserved && <><td>{row.customer_name}</td><td>{row.notes || "-"}</td></>}
        </tr>)}{!rows.length && <tr><td colSpan={reserved ? 6 : 4}>{isLoading ? t("common.loading") : t("page.search.noMatches")}</td></tr>}</tbody>
      </table>
    </div>
    <div className="mt-3 flex items-center gap-3"><span>{rows.length} / {total}</span>
      {data?.at(-1)?.has_more && <button className="btn" disabled={isValidating} onClick={() => void setSize(size => size + 1)}>{isValidating ? t("common.loading") : t("common.loadMore")}</button>}
    </div>
  </div>;
}
