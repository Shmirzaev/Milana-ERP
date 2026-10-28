"use client";

import { useDeferredValue, useState } from "react";
import useSWR from "swr";
import Modal from "@/components/Modal";
import SearchableSelect from "@/components/SearchableSelect";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";

export default function BrandedCustomerDialog({ busy, error, onClose, onCreate }: {
  busy: boolean; error: string; onClose: () => void; onCreate: (customerId: number | null) => void;
}) {
  const { t, lang } = useT();
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const search = useDeferredValue(query);
  const { data, error: loadError } = useSWR<{ id: number; name: string }[]>(`/api/planning/branded-order-customers?q=${encodeURIComponent(search)}`, fetcher);
  const optional = { en: "Customer (optional)", ru: "Клиент (необязательно)", uz: "Mijoz (ixtiyoriy)" }[lang];
  return <Modal open title={t("page.planning.newOrder")} onClose={() => { if (!busy) onClose(); }}>
    <form onSubmit={event => { event.preventDefault(); onCreate(customerId); }}>
      <label className="label" htmlFor="branded-customer">{optional}</label>
      <SearchableSelect inputId="branded-customer" value={customerId} onChange={value => setCustomerId(Number(value) || null)}
        options={(data || []).map(row => ({ value: row.id, label: row.name }))} onSearchChange={setQuery} serverFilter
        placeholder={t("warehouseReservations.selectCustomer")} noResultsText={t("page.search.noMatches")} disabled={busy} />
      {customerId && <button type="button" className="btn mt-2" disabled={busy} onClick={() => setCustomerId(null)}>{t("common.clear")}</button>}
      {(error || loadError) && <p role="alert" className="my-3 text-red-700">{error || loadError.message}</p>}
      <div className="mt-4 flex justify-end gap-2"><button type="button" className="btn" disabled={busy} onClick={onClose}>{t("common.cancel")}</button>
        <button className="btn btn-primary" disabled={busy}>{busy ? t("common.creating") : t("page.planning.newOrder")}</button></div>
    </form>
  </Modal>;
}
