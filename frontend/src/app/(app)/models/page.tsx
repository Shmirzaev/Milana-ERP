"use client";
import { useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import ConfirmDialog from "@/components/ConfirmDialog";
import PaginationControls from "@/components/PaginationControls";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type Model = {
  id: number; code: string; name: string;
  category?: string | null; description?: string | null;
  details_json?: { translation?: Record<string, string> } | null;
  status: string; created_at: string;
  sam_minutes?: number;
  primary_image_url?: string | null;
  primary_image?: {
    id: number;
    file_url: string;
    file_name?: string | null;
    content_type?: string | null;
  } | null;
  image_count?: number;
};

const STATUSES = ["draft", "sample", "approved", "archived"];

export default function ModelsPage() {
  const searchParams = useSearchParams();
  const q = searchParams.get("q")?.trim() ?? "";
  const { me } = useMe();
  const { t, lang } = useT();
  const isAdmin = can(me, "*");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(12);
  const [showFilters, setShowFilters] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [expandedActions, setExpandedActions] = useState<number | null>(null);
  const modelsUrl = `/api/models?include_total=true&page=${page}&page_size=${pageSize}${q ? `&q=${encodeURIComponent(q)}` : ""}`;
  const { data: pageData, mutate } = useSWR<any>(modelsUrl, fetcher);
  const data = useMemo<Model[]>(() => pageData?.rows || [], [pageData?.rows]);

  const [filters, setFilters] = useState({ code: "", name: "", category: "" });
  const [form, setForm] = useState({ code: "", name: "", category: "", sam_minutes: 0 });
  const [err, setErr] = useState("");

  const [editing, setEditing] = useState<Model | null>(null);
  const [edit, setEdit] = useState({ code: "", name: "", category: "", description: "", status: "draft", sam_minutes: 0 });
  const [editMsg, setEditMsg] = useState("");
  const [deleting, setDeleting] = useState<Model | null>(null);

  const rows = useMemo(() => {
    const codeQ = filters.code.trim().toLowerCase();
    const nameQ = filters.name.trim().toLowerCase();
    const categoryQ = filters.category.trim().toLowerCase();
    return (data ?? []).filter((m) => {
      if (codeQ && !String(m.code || "").toLowerCase().includes(codeQ)) return false;
      if (nameQ && !String(m.name || "").toLowerCase().includes(nameQ)) return false;
      if (categoryQ && !String(m.category || "").toLowerCase().includes(categoryQ)) return false;
      return true;
    });
  }, [data, filters.category, filters.code, filters.name]);

  function displayModelName(m: any) {
    const tr = m.details_json?.translation || {};
    return tr[lang] || (lang === "ru" ? tr.ru : "") || m.name;
  }

  function previewImageUrl(m: Model) {
    const image = m.primary_image;
    const contentType = String(image?.content_type || "").toLowerCase();
    const fileName = String(image?.file_name || image?.file_url || m.primary_image_url || "").toLowerCase();
    const looksLikeImage = contentType.startsWith("image/") || /\.(png|jpe?g|webp|gif)$/i.test(fileName);
    const imageUrl = image?.file_url && looksLikeImage ? image.file_url : m.primary_image_url || "";
    const match = imageUrl.match(/^\/storage\/model-files\/([^/?#]+)$/);
    if (match) return `/storage/model-files/thumb/${match[1]}?size=320`;
    return imageUrl;
  }

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    try { await api.post("/api/models", form); setForm({ code: "", name: "", category: "", sam_minutes: 0 }); mutate(); }
    catch (e: any) { setErr(e.message); }
  }
  async function approve(id: number) { await api.post(`/api/models/${id}/approve`); mutate(); }
  function openEdit(m: Model) {
    setEditing(m);
    setEdit({ code: m.code, name: m.name, category: m.category ?? "", description: m.description ?? "", status: m.status, sam_minutes: Number(m.sam_minutes ?? 0) });
    setEditMsg("");
  }
  async function saveEdit(e: React.FormEvent) {
    e.preventDefault();
    if (!editing) return;
    setEditMsg("");
    try { await api.patch(`/api/models/${editing.id}`, edit); setEditing(null); mutate(); }
    catch (e: any) { setEditMsg(e.message); }
  }

  function removeModel(m: Model) {
    setDeleting(m);
  }

  async function confirmRemoveModel() {
    if (!deleting) return;
    try {
      await api.del(`/api/models/${deleting.id}`);
      if (editing?.id === deleting.id) setEditing(null);
      setDeleting(null);
      mutate();
    } catch (e: any) {
      alert(e.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.models.title")} subtitle={t("page.models.subtitle")} />
      <div className="mb-3 flex flex-wrap gap-2 md:hidden">
        <button type="button" className="btn flex-1 justify-center" onClick={() => setShowFilters((open) => !open)}>
          {showFilters ? t("page.models.hideFilters") : t("page.models.showFilters")}
        </button>
        <button type="button" className="btn btn-primary flex-1 justify-center" onClick={() => setShowCreate((open) => !open)}>
          {showCreate ? t("page.models.hideCreate") : t("page.models.showCreate")}
        </button>
      </div>
      <form onSubmit={(e) => e.preventDefault()} className={`${showFilters ? "grid" : "hidden"} card mb-4 grid-cols-1 gap-3 p-4 md:grid md:grid-cols-3`}>
        <input
          className="input"
          placeholder={t("common.code")}
          value={filters.code}
          onChange={(e) => setFilters((prev) => ({ ...prev, code: e.target.value }))}
        />
        <input
          className="input"
          placeholder={t("common.name")}
          value={filters.name}
          onChange={(e) => setFilters((prev) => ({ ...prev, name: e.target.value }))}
        />
        <input
          className="input"
          placeholder={t("field.category")}
          value={filters.category}
          onChange={(e) => setFilters((prev) => ({ ...prev, category: e.target.value }))}
        />
      </form>
      <form onSubmit={create} className={`${showCreate ? "grid" : "hidden"} card mb-6 grid-cols-1 gap-3 p-4 md:grid md:grid-cols-5`}>
        <input className="input" placeholder={t("common.code")} value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
        <input className="input" placeholder={t("common.name")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
        <input className="input" placeholder={t("field.category")} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} />
        <input className="input" type="number" step="0.1" placeholder={t("field.samMinutes")} value={form.sam_minutes} onChange={(e) => setForm({ ...form, sam_minutes: Number(e.target.value) })} title={t("field.samHint")} />
        <button className="btn btn-primary">{t("btn.createDraftModel")}</button>
        {err && <div className="md:col-span-5 text-sm text-red-600">{err}</div>}
      </form>
      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {rows.map((m) => {
          const imageUrl = previewImageUrl(m);
          const modelName = displayModelName(m);
          const hasSecondaryActions = m.status !== "approved" || isAdmin;
          const actionsOpen = expandedActions === m.id;
          return (
            <article key={m.id} className="overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] shadow-sm transition hover:border-[#d6ceb9] hover:shadow-md">
              <div className="grid min-h-[172px] grid-cols-[112px_minmax(0,1fr)] sm:grid-cols-[140px_minmax(0,1fr)]">
                <Link href={`/models/${m.id}`} className="block h-full bg-[#f1efe8]">
                  {imageUrl ? (
                    <img
                      src={imageUrl}
                      alt={modelName}
                      className="h-full min-h-[172px] w-full object-cover"
                      loading="lazy"
                      decoding="async"
                      width={320}
                      height={320}
                    />
                  ) : (
                    <div className="flex h-full min-h-[172px] flex-col items-center justify-center gap-2 border-r border-[#e3dfd3] px-3 text-center">
                      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[#ded9ca] bg-[#fdfcf8] text-sm font-semibold text-[#56503f]">
                        {String(m.code || modelName || "?").slice(0, 2).toUpperCase()}
                      </div>
                      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-[#8a8472]">{t("page.models.noPreview")}</div>
                    </div>
                  )}
                </Link>
                <div className="flex min-w-0 flex-col p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="mono text-xs font-semibold uppercase text-[#8a8472]">{m.code}</div>
                      <Link href={`/models/${m.id}`} className="mt-1 block break-words text-base font-semibold leading-snug text-[#14110b] hover:underline">
                        {modelName}
                      </Link>
                    </div>
                    <span className={`badge shrink-0 ${m.status === "approved" ? "badge-green" : "badge-yellow"}`}>{t(`modelStatus.${m.status}`)}</span>
                  </div>

                  <dl className="mt-4 grid grid-cols-1 gap-2 text-xs text-[#56503f] sm:grid-cols-3">
                    <div>
                      <dt className="label mb-0">{t("field.category")}</dt>
                      <dd className="truncate">{m.category || "-"}</dd>
                    </div>
                    <div>
                      <dt className="label mb-0">{t("field.sam")}</dt>
                      <dd>{Number(m.sam_minutes ?? 0)}</dd>
                    </div>
                    <div>
                      <dt className="label mb-0">{t("field.created")}</dt>
                      <dd>{new Date(m.created_at).toLocaleDateString()}</dd>
                    </div>
                  </dl>

                  <div className="mt-auto pt-4 text-sm">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
                      <Link href={`/models/${m.id}`} className="font-medium text-brand-600 hover:underline">{t("btn.view")}</Link>
                      {hasSecondaryActions && (
                        <button
                          type="button"
                          className="font-medium text-[#56503f] hover:underline sm:hidden"
                          onClick={() => setExpandedActions(actionsOpen ? null : m.id)}
                          aria-expanded={actionsOpen}
                        >
                          {t("common.actions")}
                        </button>
                      )}
                    </div>
                    {hasSecondaryActions && (
                      <div className={`${actionsOpen ? "flex" : "hidden"} mt-2 flex-wrap items-center gap-x-3 gap-y-2 sm:flex`}>
                        {m.status !== "approved" && (
                          <button type="button" className="font-medium text-green-700 hover:underline" onClick={() => approve(m.id)}>{t("btn.approve")}</button>
                        )}
                        {isAdmin && (
                          <>
                            <button type="button" className="font-medium text-slate-700 hover:underline" onClick={() => openEdit(m)}>{t("btn.edit")}</button>
                            <button type="button" className="font-medium text-red-600 hover:underline" onClick={() => removeModel(m)}>{t("common.delete")}</button>
                          </>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            </article>
          );
        })}
        {rows.length === 0 && (
          <div className="rounded-lg border border-dashed border-[#ded9ca] bg-[#fdfcf8] p-8 text-center text-sm text-[#8a8472]">
            {t("page.models.empty")}
          </div>
        )}
      </div>
      <PaginationControls
        page={page}
        pageSize={pageSize}
        total={Number(pageData?.total || rows.length)}
        count={data.length}
        onPageChange={setPage}
        onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
      />

      <Modal open={!!editing} onClose={() => setEditing(null)} title={t("page.models.editTitle", { code: editing?.code ?? "" })} wide>
        <form onSubmit={saveEdit} className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">{t("common.code")}</label><input className="input" value={edit.code} onChange={(e) => setEdit({ ...edit, code: e.target.value })} required /></div>
            <div><label className="label">{t("common.name")}</label><input className="input" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} required /></div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><label className="label">{t("field.category")}</label><input className="input" value={edit.category} onChange={(e) => setEdit({ ...edit, category: e.target.value })} /></div>
            <div>
              <label className="label">{t("field.status")}</label>
              <select className="input" value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                {STATUSES.map((s) => <option key={s} value={s}>{t(`modelStatus.${s}`)}</option>)}
              </select>
            </div>
            <div>
              <label className="label" title={t("field.samHint")}>{t("field.samMinutes")}</label>
              <input className="input" type="number" step="0.1" value={edit.sam_minutes} onChange={(e) => setEdit({ ...edit, sam_minutes: Number(e.target.value) })} />
            </div>
          </div>
          <div><label className="label">{t("field.description")}</label><textarea className="input" rows={3} value={edit.description} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></div>
          {editMsg && <div className="text-sm text-red-600">{editMsg}</div>}
          <div className="flex justify-end gap-2 pt-2">
            <button type="button" className="btn" onClick={() => setEditing(null)}>{t("btn.cancel")}</button>
            <button type="submit" className="btn btn-primary">{t("btn.saveChanges")}</button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        isOpen={!!deleting}
        title={t("confirm.deleteTitle")}
        message={deleting ? t("confirm.deleteModel", { name: deleting.code }) : ""}
        onConfirm={confirmRemoveModel}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}
