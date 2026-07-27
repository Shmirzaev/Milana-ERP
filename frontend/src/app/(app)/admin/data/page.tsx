"use client";
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { Database, Pencil, RefreshCw, Search, ShieldCheck, Trash2 } from "lucide-react";
import { api, fetcher } from "@/lib/api";
import ConfirmDialog from "@/components/ConfirmDialog";
import Modal from "@/components/Modal";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type Column = {
  name: string;
  type: string;
  nullable: boolean;
  primary_key: boolean;
  foreign_key: string | null;
  editable: boolean;
};

type TableInfo = {
  name: string;
  label: string;
  row_count: number;
  columns: Column[];
};

type RowsResponse = {
  table: string;
  label: string;
  columns: Column[];
  rows: Record<string, any>[];
  total: number;
  page: number;
  page_size: number;
};

const PAGE_SIZE = 50;
const IDENTIFIER_KEYS = ["order_no", "production_no", "work_order_no", "bundle_no", "package_no", "code", "sku", "name", "email"];

function typeIncludes(column: Column, ...needles: string[]) {
  const lower = column.type.toLowerCase();
  return needles.some((needle) => lower.includes(needle));
}

function isJsonColumn(column: Column) {
  return typeIncludes(column, "json");
}

function isBooleanColumn(column: Column) {
  return typeIncludes(column, "bool");
}

function isNumberColumn(column: Column) {
  return typeIncludes(column, "int", "numeric", "decimal", "float", "double");
}

function isBinaryValue(value: any) {
  return Boolean(value && typeof value === "object" && value.__binary);
}

function toCellText(value: any) {
  if (value === null || value === undefined || value === "") return "NULL";
  if (isBinaryValue(value)) return `Binary ${value.size ?? 0} B`;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function compactCell(value: any) {
  const text = toCellText(value);
  return text.length > 90 ? `${text.slice(0, 87)}...` : text;
}

function stable(value: any) {
  return JSON.stringify(value ?? null);
}

function rowTitle(row: Record<string, any>, tableName: string) {
  const id = row.id ?? "-";
  const found = IDENTIFIER_KEYS.map((key) => row[key]).find((value) => value !== undefined && value !== null && value !== "");
  return found ? `${tableName} #${id} (${found})` : `${tableName} #${id}`;
}

function draftValue(column: Column, value: any) {
  if (value === null || value === undefined) return "";
  if (isJsonColumn(column)) return typeof value === "string" ? value : JSON.stringify(value, null, 2);
  if (typeof value === "object" && !isBinaryValue(value)) return JSON.stringify(value, null, 2);
  return String(value);
}

function parseDraftValue(column: Column, value: any) {
  if (value === null) return null;
  if (isBooleanColumn(column)) return Boolean(value);
  if (isJsonColumn(column)) {
    if (typeof value !== "string") return value;
    const trimmed = value.trim();
    if (!trimmed) return column.nullable ? null : {};
    return JSON.parse(trimmed);
  }
  if (isNumberColumn(column)) {
    if (value === "" || value === undefined) return column.nullable ? null : value;
    return Number(value);
  }
  return value;
}

export default function SuperDataPage() {
  const { t } = useT();
  const { data: tables, mutate: mutateTables } = useSWR<TableInfo[]>("/api/admin/super-data/tables", fetcher);
  const [selectedTable, setSelectedTable] = useState("");
  const [tableFilter, setTableFilter] = useState("");
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [editing, setEditing] = useState<Record<string, any> | null>(null);
  const [draft, setDraft] = useState<Record<string, any>>({});
  const [editMsg, setEditMsg] = useState("");
  const [deleting, setDeleting] = useState<Record<string, any> | null>(null);
  const [deleteMsg, setDeleteMsg] = useState("");

  useEffect(() => {
    if (!selectedTable && tables?.length) setSelectedTable(tables[0].name);
  }, [selectedTable, tables]);

  useEffect(() => {
    setPage(1);
    setSearch("");
    setQuery("");
  }, [selectedTable]);

  const rowsKey = selectedTable
    ? `/api/admin/super-data/tables/${selectedTable}?page=${page}&page_size=${PAGE_SIZE}&q=${encodeURIComponent(query)}`
    : null;
  const { data: grid, mutate: mutateRows, isLoading, error } = useSWR<RowsResponse>(rowsKey, fetcher);
  const activeTable = useMemo(() => tables?.find((table) => table.name === selectedTable), [selectedTable, tables]);
  const columns = grid?.columns ?? activeTable?.columns ?? [];
  const totalPages = Math.max(1, Math.ceil((grid?.total ?? 0) / PAGE_SIZE));
  const editableColumns = columns.filter((column) => column.editable);

  const filteredTables = useMemo(() => {
    const needle = tableFilter.trim().toLowerCase();
    if (!tables) return [];
    if (!needle) return tables;
    return tables.filter((table) => table.name.toLowerCase().includes(needle) || table.label.toLowerCase().includes(needle));
  }, [tableFilter, tables]);

  function refreshAll() {
    mutateTables();
    mutateRows();
  }

  function submitSearch(e: React.FormEvent) {
    e.preventDefault();
    setPage(1);
    setQuery(search.trim());
  }

  function openEdit(row: Record<string, any>) {
    const nextDraft: Record<string, any> = {};
    for (const column of columns) {
      nextDraft[column.name] = isBooleanColumn(column) ? Boolean(row[column.name]) : row[column.name] ?? "";
    }
    setEditing(row);
    setDraft(nextDraft);
    setEditMsg("");
  }

  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing || !selectedTable) return;
    setEditMsg("");
    try {
      const values: Record<string, any> = {};
      for (const column of editableColumns) {
        const parsed = parseDraftValue(column, draft[column.name]);
        if (stable(parsed) !== stable(editing[column.name])) values[column.name] = parsed;
      }
      await api.patch(`/api/admin/super-data/tables/${selectedTable}/rows/${editing.id}`, { values });
      setEditing(null);
      mutateRows();
      mutateTables();
    } catch (err: any) {
      setEditMsg(err?.message || t("page.superData.updateFailed"));
    }
  }

  async function confirmDelete() {
    if (!deleting || !selectedTable) return;
    setDeleteMsg("");
    try {
      await api.del(`/api/admin/super-data/tables/${selectedTable}/rows/${deleting.id}`);
      setDeleting(null);
      mutateRows();
      mutateTables();
    } catch (err: any) {
      setDeleteMsg(err?.message || t("page.superData.deleteFailed"));
    }
  }

  return (
    <div>
      <PageHeader
        title={t("page.superData.title")}
        subtitle={t("page.superData.subtitle")}
        actions={
          <button type="button" className="btn" onClick={refreshAll}>
            <RefreshCw />
            {t("btn.refresh")}
          </button>
        }
      />

      <div className="mb-4 rounded-md border border-[#ded9ca] bg-[#f8f6ef] px-4 py-3 text-sm text-[#56503f]">
        <div className="flex items-start gap-2">
          <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-[#14110b]" />
          <p>{t("page.superData.notice")}</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
        <aside className="card">
          <div className="border-b border-[#e3dfd3] p-3">
            <label className="label" htmlFor="table-filter">{t("page.superData.tables")}</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-[#8a8472]" />
              <input
                id="table-filter"
                className="input pl-9"
                value={tableFilter}
                onChange={(e) => setTableFilter(e.target.value)}
                placeholder={t("page.superData.searchTables")}
              />
            </div>
          </div>
          <div className="max-h-[520px] overflow-y-auto p-2">
            {filteredTables.map((table) => (
              <button
                key={table.name}
                type="button"
                className={`mb-1 flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm ${
                  selectedTable === table.name
                    ? "bg-[#14110b] text-[#fdfcf8]"
                    : "text-[#2c2920] hover:bg-[#f1efe8]"
                }`}
                onClick={() => setSelectedTable(table.name)}
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">{table.label}</span>
                  <span className={`block truncate text-xs ${selectedTable === table.name ? "text-[#d8d2c2]" : "text-[#8a8472]"}`}>
                    {table.name}
                  </span>
                </span>
                <span className={`mono shrink-0 text-xs ${selectedTable === table.name ? "text-[#d8d2c2]" : "text-[#8a8472]"}`}>
                  {table.row_count}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="min-w-0">
          <div className="card mb-4 p-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <Database className="h-5 w-5 text-[#56503f]" />
                  <h2 className="app-card-title text-base">{grid?.label ?? activeTable?.label ?? t("page.superData.noTable")}</h2>
                </div>
                <p className="mt-1 text-sm text-[#8a8472]">
                  {selectedTable ? t("page.superData.tableMeta", { columns: columns.length, rows: grid?.total ?? activeTable?.row_count ?? 0 }) : ""}
                </p>
              </div>
              <form onSubmit={submitSearch} className="flex w-full gap-2 lg:max-w-md">
                <input
                  className="input"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("page.superData.searchRows")}
                />
                <button type="submit" className="btn btn-primary">
                  <Search />
                  {t("common.search")}
                </button>
              </form>
            </div>
          </div>

          {error ? (
            <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{String(error.message || error)}</div>
          ) : null}

          <div className="card overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("common.actions")}</th>
                  {columns.map((column) => (
                    <th key={column.name} title={column.foreign_key ?? column.type}>
                      <span className="block">{column.name}</span>
                      <span className="block text-[10px] font-normal normal-case tracking-normal">{column.type}</span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {isLoading ? (
                  <tr><td colSpan={columns.length + 1}>{t("common.loading")}</td></tr>
                ) : (grid?.rows ?? []).length ? (
                  grid?.rows.map((row) => (
                    <tr key={row.id}>
                      <td>
                        <div className="flex items-center gap-2">
                          <button type="button" className="icon-btn" title={t("common.edit")} onClick={() => openEdit(row)}>
                            <Pencil />
                          </button>
                          <button type="button" className="icon-btn text-red-600" title={t("common.delete")} onClick={() => setDeleting(row)}>
                            <Trash2 />
                          </button>
                        </div>
                      </td>
                      {columns.map((column) => (
                        <td key={`${row.id}-${column.name}`} className="max-w-[280px]">
                          <span className={row[column.name] === null || row[column.name] === undefined ? "text-[#8a8472]" : ""} title={toCellText(row[column.name])}>
                            {compactCell(row[column.name])}
                          </span>
                        </td>
                      ))}
                    </tr>
                  ))
                ) : (
                  <tr><td colSpan={columns.length + 1}>{t("page.superData.empty")}</td></tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-[#56503f]">
            <span>{t("common.showingRange", { start: grid?.rows.length ? (page - 1) * PAGE_SIZE + 1 : 0, end: (page - 1) * PAGE_SIZE + (grid?.rows.length ?? 0), total: grid?.total ?? 0 })}</span>
            <div className="flex items-center gap-2">
              <button type="button" className="btn" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
                {t("common.previous")}
              </button>
              <span className="mono text-xs">{page} / {totalPages}</span>
              <button type="button" className="btn" disabled={page >= totalPages} onClick={() => setPage((current) => current + 1)}>
                {t("common.next")}
              </button>
            </div>
          </div>
        </section>
      </div>

      <Modal open={!!editing} onClose={() => setEditing(null)} title={editing ? rowTitle(editing, selectedTable) : ""} wide>
        <form onSubmit={saveEdit} className="space-y-4">
          <div className="max-h-[62vh] space-y-3 overflow-y-auto pr-1">
            {columns.map((column) => {
              const value = draft[column.name];
              return (
                <div key={column.name} className="rounded-md border border-[#e3dfd3] bg-[#fdfcf8] p-3">
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <label className="label mb-0">{column.name}</label>
                    <div className="flex items-center gap-2">
                      {column.primary_key ? <span className="badge">{t("page.superData.primaryKey")}</span> : null}
                      {column.foreign_key ? <span className="badge">{column.foreign_key}</span> : null}
                      {column.nullable && column.editable ? (
                        <button type="button" className="btn h-7 px-2" onClick={() => setDraft((current) => ({ ...current, [column.name]: null }))}>
                          NULL
                        </button>
                      ) : null}
                    </div>
                  </div>
                  {!column.editable ? (
                    <pre className="max-h-32 overflow-auto rounded-md bg-[#f1efe8] p-2 text-xs text-[#56503f]">{toCellText(editing?.[column.name])}</pre>
                  ) : isBooleanColumn(column) ? (
                    <label className="flex items-center gap-2 text-sm text-[#2c2920]">
                      <input
                        type="checkbox"
                        checked={Boolean(value)}
                        onChange={(e) => setDraft((current) => ({ ...current, [column.name]: e.target.checked }))}
                      />
                      {Boolean(value) ? t("field.yes") : t("field.no")}
                    </label>
                  ) : isJsonColumn(column) ? (
                    <textarea
                      className="input min-h-32 font-mono text-xs"
                      value={value === null ? "null" : draftValue(column, value)}
                      onChange={(e) => setDraft((current) => ({ ...current, [column.name]: e.target.value }))}
                    />
                  ) : (
                    <input
                      className="input"
                      type={isNumberColumn(column) ? "number" : "text"}
                      step={isNumberColumn(column) ? "any" : undefined}
                      value={value === null ? "" : draftValue(column, value)}
                      onChange={(e) => setDraft((current) => ({ ...current, [column.name]: e.target.value }))}
                    />
                  )}
                </div>
              );
            })}
          </div>
          {editMsg ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{editMsg}</div> : null}
          <div className="flex justify-end gap-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{t("common.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("common.save")}</button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        isOpen={!!deleting}
        title={t("confirm.deleteTitle")}
        message={deleting ? t("page.superData.deleteConfirm", { row: rowTitle(deleting, selectedTable) }) : ""}
        confirmText={t("common.delete")}
        onConfirm={confirmDelete}
        onCancel={() => {
          setDeleting(null);
          setDeleteMsg("");
        }}
      />
      {deleteMsg ? <div className="fixed bottom-4 right-4 z-50 rounded-md bg-red-50 p-3 text-sm text-red-700 shadow-sm">{deleteMsg}</div> : null}
    </div>
  );
}
