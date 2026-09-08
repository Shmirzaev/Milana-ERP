"use client";

import { useState } from "react";
import { useT } from "@/lib/i18n";
import { storageThumbnailUrl } from "@/lib/modelImages";
import { packagingNumericColumns, type PackagingReportRow } from "@/lib/packagingReport";

export default function PackagingReportTable({ rows, columns, pictures }: {
  rows: PackagingReportRow[]; columns: readonly string[]; pictures: boolean;
}) {
  const { t } = useT();
  const [visible, setVisible] = useState(100);
  if (rows.length === 0) return <p className="py-6 text-sm text-[#6d6758]">{t("packagingReport.empty")}</p>;
  return (
    <>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={t("packagingReport.title")}>
        <table className="table min-w-full">
          <thead><tr><th>№</th>{pictures && <th>{t("field.picture")}</th>}
            {columns.map((column) => <th key={column} className={packagingNumericColumns.has(column) ? "text-right" : ""}>{t(`packagingReport.${column}`)}</th>)}
          </tr></thead>
          <tbody>{rows.slice(0, visible).map((row, index) => (
            <tr key={index}>
              <td>{index + 1}</td>
              {pictures && <td>{row.image_url ? <img className="h-14 w-14 max-w-none object-contain" loading="lazy" src={storageThumbnailUrl(String(row.image_url), 160)} alt={String(row.model_no || "")} /> : "—"}</td>}
              {columns.map((column) => <td key={column} className={packagingNumericColumns.has(column) ? "min-w-24 text-right tabular-nums" : column === "date" ? "min-w-32 whitespace-nowrap" : "min-w-24"}>
                {typeof row[column] === "number" ? row[column].toLocaleString() : row[column] || "—"}
              </td>)}
            </tr>
          ))}</tbody>
          <tfoot><tr className="font-semibold"><td>{t("packagingReport.total")}</td>{pictures && <td />}
            {columns.map((column) => {
              const values = rows.map((row) => row[column]).filter((value): value is number => typeof value === "number");
              return <td key={column} className="text-right tabular-nums">{packagingNumericColumns.has(column) && values.length ? values.reduce((sum, value) => sum + value, 0).toLocaleString() : ""}</td>;
            })}
          </tr></tfoot>
        </table>
      </div>
      {rows.length > visible && <button type="button" className="btn mt-3" onClick={() => setVisible((count) => count + 100)}>{t("packagingReport.more")} ({visible}/{rows.length})</button>}
    </>
  );
}
