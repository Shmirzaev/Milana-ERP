"use client";

import { formatVariantNumber } from "@/lib/variantDisplay";
import { useT } from "@/lib/i18n";
import { storageThumbnailUrl } from "@/lib/modelImages";
import { packagingNumericColumns, type PackagingReportPageRow } from "@/lib/packagingReport";

export default function PackagingReportTable({ rows, columns, pictures, summary, offset }: {
  rows: PackagingReportPageRow[]; columns: readonly string[]; pictures: boolean; summary: Record<string, number | null>; offset: number;
}) {
  const { t } = useT();
  if (rows.length === 0) return <p className="py-6 text-sm text-[#6d6758]">{t("packagingReport.empty")}</p>;
  return (
    <>
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label={t("packagingReport.title")}>
        <table className="table min-w-full">
          <thead><tr><th>№</th>{pictures && <th>{t("field.picture")}</th>}
            {columns.map((column) => <th key={column} className={packagingNumericColumns.has(column) ? "text-right" : ""}>{t(`packagingReport.${column}`)}</th>)}
          </tr></thead>
          <tbody>{rows.map((row, index) => (
            <tr key={row.row_key}>
              <td>{offset + index + 1}</td>
              {pictures && <td>{row.image_url ? <img className="h-14 w-14 max-w-none object-contain" loading="lazy" src={storageThumbnailUrl(String(row.image_url), 160)} alt={String(row.model_no || "")} /> : "—"}</td>}
              {columns.map((column) => <td key={column} className={packagingNumericColumns.has(column) ? "min-w-24 text-right tabular-nums" : column === "date" ? "min-w-32 whitespace-nowrap" : "min-w-24"}>
                {column === "variant_no" ? formatVariantNumber(row[column]) || "—" : typeof row[column] === "number" ? row[column].toLocaleString() : row[column] || "—"}
              </td>)}
            </tr>
          ))}</tbody>
          <tfoot><tr className="font-semibold"><td>{t("packagingReport.total")}</td>{pictures && <td />}
            {columns.map((column) => {
              const value = summary[column];
              return <td key={column} className="text-right tabular-nums">{packagingNumericColumns.has(column) && typeof value === "number" ? value.toLocaleString() : ""}</td>;
            })}
          </tr></tfoot>
        </table>
      </div>
    </>
  );
}
