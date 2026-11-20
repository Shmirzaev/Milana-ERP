"use client";

import { useState } from "react";
import useSWR from "swr";
import { fetcher } from "@/lib/api";
import { cuttingLabelsText, cuttingPiecesText, type CuttingBalance } from "@/lib/cuttingBalance";
import { cuttingHandoffText, handoffFactoryName, type HandoffFactory } from "@/lib/cuttingHandoff";
import { useT } from "@/lib/i18n";
import { departmentMessages } from "@/components/dashboard/departmentMessages";
import { formatOrderReference } from "@/lib/orderRef";

type FactoryBalance = CuttingBalance & {
  factory: HandoffFactory;
  orders: (CuttingBalance & { order_no: string })[];
};

export default function CuttingStorageByOrder({ department }: { department: string }) {
  const { t, lang } = useT();
  const copy = cuttingHandoffText[lang];
  const [expanded, setExpanded] = useState<Partial<Record<HandoffFactory, boolean>>>({});
  const { data, error, isLoading } = useSWR<FactoryBalance[]>(
    `/api/bundles/cutting-storage-by-order?cutting_department_code=${department}`, fetcher,
  );
  return <section className="mb-4" aria-labelledby="cutting-storage-heading">
    <h2 id="cutting-storage-heading" className="app-card-title mb-2">{copy.stock}</h2>
    {error && <p role="alert" className="text-red-700">{error.message}</p>}
    {isLoading && <p role="status">{t("common.loading")}</p>}
    <div className="grid gap-3 md:grid-cols-2">
      {data?.map((factory) => <div key={factory.factory} className="card p-4">
        <h3 className="font-semibold">{handoffFactoryName[factory.factory]}</h3>
        <p className="mt-1 text-sm tabular-nums">
          {cuttingPiecesText(factory)} {copy.pieces} · {cuttingLabelsText(factory)} {departmentMessages[lang].originalLabels}
        </p>
        {factory.orders.length ? <>
          <table className="table mt-2">
            <thead><tr><th>{copy.order}</th><th>{copy.pieces}</th><th>{departmentMessages[lang].originalLabels}</th></tr></thead>
            <tbody>{(expanded[factory.factory] ? factory.orders : factory.orders.slice(0, 10)).map(order => (
              <tr key={order.order_no}>
                <td>{formatOrderReference(order.order_no)}</td>
                <td className="tabular-nums">{cuttingPiecesText(order)}</td>
                <td className="tabular-nums">{cuttingLabelsText(order)}</td>
              </tr>
            ))}</tbody>
          </table>
          {factory.orders.length > 10 && <button className="btn mt-3" type="button"
            aria-expanded={Boolean(expanded[factory.factory])}
            onClick={() => setExpanded(previous => ({ ...previous, [factory.factory]: !previous[factory.factory] }))}>
            {expanded[factory.factory] ? copy.fewer : copy.more}
          </button>}
        </> : <p className="mt-2 text-sm text-slate-500">{copy.emptyStock}</p>}
      </div>)}
    </div>
  </section>;
}
