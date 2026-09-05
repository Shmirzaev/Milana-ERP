"use client";
import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import useSWR from "swr";
import { fetcher, api } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import ConfirmDialog from "@/components/ConfirmDialog";
import PaginationControls from "@/components/PaginationControls";
import { useMe, can } from "@/lib/auth";
import { useT } from "@/lib/i18n";
import { useDialogs } from "@/components/DialogProvider";
import { type MaterialComposition } from "@/lib/materialComposition";
import { formatModelComposition } from "@/lib/modelComposition";
import { modelCodeParts } from "@/lib/modelCode";
import { isPreviewModelImage, storageThumbnailUrl } from "@/lib/modelImages";
import { modelVariantOption } from "@/lib/modelVariants";
import VerticalModelPhoto from "@/components/VerticalModelPhoto";

type Model = {
  id: number; code: string; name: string;
  category?: string | null; description?: string | null;
  details_json?: {
    general?: {
      model_no?: string | null;
      variant_no?: string | null;
    } | null;
    translation?: Record<string, string>;
    composition?: MaterialComposition[] | null;
  } | null;
  status: string; created_at: string;
  sam_minutes?: number;
  material_composition?: MaterialComposition[] | null;
  primary_image_url?: string | null;
  variant_fabric?: string | null;
  variant_picture_url?: string | null;
  group_key?: string | null;
  group_model_no?: string | null;
  group_name?: string | null;
  variant_count?: number;
  variants?: Array<Model & {
    model_id?: number;
    model_no?: string | null;
    variant_no?: string | null;
    fabric?: string | null;
    picture_url?: string | null;
  }>;
  primary_image?: {
    id: number;
    file_url: string;
    file_name?: string | null;
    content_type?: string | null;
  } | null;
  image_count?: number;
};

type ModelsPageData = {
  rows?: Model[];
  total?: number;
};

export default function ModelsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const q = searchParams.get("q")?.trim() ?? "";
  const { me } = useMe();
  const { t, lang } = useT();
  const dialogs = useDialogs();
  const isUsluga = pathname.startsWith("/usluga/models");
  const modelApiBase = isUsluga ? "/api/usluga/models" : "/api/models";
  const modelPageBase = isUsluga ? "/usluga/models" : "/models";
  const canManage = isUsluga ? can(me, "usluga.manage", "*") : can(me, "modeling.models", "*");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(100);
  const [showFilters, setShowFilters] = useState(false);
  const [cloningId, setCloningId] = useState<number | null>(null);
  const [filters, setFilters] = useState({ code: "", name: "", category: "", createdFrom: "", createdTo: "" });
  const [appliedFilters, setAppliedFilters] = useState(filters);

  useEffect(() => {
    const timer = window.setTimeout(() => setAppliedFilters(filters), 180);
    return () => window.clearTimeout(timer);
  }, [filters]);

  const modelsUrl = useMemo(() => {
    const params = new URLSearchParams({
      compact: "true",
      include_total: "true",
      page: String(page),
      page_size: String(pageSize),
    });
    if (q) params.set("q", q);
    if (appliedFilters.code) params.set("code", appliedFilters.code);
    if (appliedFilters.name) params.set("name", appliedFilters.name);
    if (appliedFilters.category) params.set("category", appliedFilters.category);
    if (appliedFilters.createdFrom) params.set("created_from", appliedFilters.createdFrom);
    if (appliedFilters.createdTo) params.set("created_to", appliedFilters.createdTo);
    return `${modelApiBase}/variant-groups?${params.toString()}`;
  }, [appliedFilters, modelApiBase, page, pageSize, q]);
  const {
    data: pageData,
    error,
    isLoading,
    isValidating,
    mutate,
  } = useSWR<ModelsPageData>(modelsUrl, fetcher, { keepPreviousData: true });
  const data = useMemo<Model[]>(() => pageData?.rows ?? [], [pageData?.rows]);

  const [deleting, setDeleting] = useState<Model | null>(null);

  useEffect(() => {
    setPage(1);
  }, [filters, q]);

  const rows = data;
  const showInitialLoading = !pageData && !error && (isLoading || isValidating);
  const showRefreshLoading = Boolean(pageData) && isValidating;
  const showEmpty = Boolean(pageData) && !error && !isValidating && rows.length === 0;

  function displayModelName(m: any) {
    if (m.group_name) return m.group_name;
    const tr = m.details_json?.translation || {};
    return tr[lang] || (lang === "ru" ? tr.ru : "") || m.name;
  }

  function previewImageUrl(m: Model) {
    const image = m.primary_image;
    const imageUrl = image?.file_url && isPreviewModelImage(image) ? image.file_url : m.primary_image_url || "";
    return storageThumbnailUrl(imageUrl, 320);
  }

  function variantThumbUrl(variant: NonNullable<Model["variants"]>[number]) {
    return storageThumbnailUrl(variant.picture_url || variant.variant_picture_url || variant.primary_image_url || "", 160);
  }

  async function approve(id: number) { await api.post(`${modelApiBase}/${id}/approve`); mutate(); }

  async function cloneModel(m: Model) {
    setCloningId(m.id);
    try {
      const cloned = await api.post<Model>(`${modelApiBase}/${m.id}/clone`);
      router.push(`${modelPageBase}/${cloned.id}?mode=edit`);
    } catch (e: any) {
      await dialogs.notify(e.message);
    } finally {
      setCloningId(null);
    }
  }

  function removeModel(m: Model) {
    setDeleting(m);
  }

  async function confirmRemoveModel() {
    if (!deleting) return;
    try {
      await api.del(`${modelApiBase}/${deleting.id}`);
      setDeleting(null);
      mutate();
    } catch (e: any) {
      await dialogs.notify(e.message);
    }
  }

  return (
    <div>
      <PageHeader
        title={isUsluga ? t("usluga.modelsTitle") : t("page.models.title")}
        subtitle={isUsluga ? t("usluga.modelsSubtitle") : t("page.models.subtitle")}
        actions={canManage ? <Link href={`${modelPageBase}/new`} className="btn btn-primary">{t("page.models.createNew")}</Link> : null}
      />
      <div className="mb-3 flex flex-wrap gap-2 md:hidden">
        <button type="button" className="btn flex-1 justify-center" onClick={() => setShowFilters((open) => !open)}>
          {showFilters ? t("page.models.hideFilters") : t("page.models.showFilters")}
        </button>
        {canManage && <Link href={`${modelPageBase}/new`} className="btn btn-primary flex-1 justify-center">{t("page.models.createNew")}</Link>}
      </div>
      <form onSubmit={(e) => e.preventDefault()} className={`${showFilters ? "grid" : "hidden"} card mb-4 grid-cols-1 gap-3 p-4 md:grid md:grid-cols-5`}>
        <input
          className="input"
          placeholder={`${t("field.modelNo")} / ${t("field.variantNo")}`}
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
        <label className="block">
          <span className="label">{t("common.createdFrom")}</span>
          <input
            className="input"
            type="date"
            value={filters.createdFrom}
            onChange={(e) => setFilters((prev) => ({ ...prev, createdFrom: e.target.value }))}
          />
        </label>
        <label className="block">
          <span className="label">{t("common.createdTo")}</span>
          <input
            className="input"
            type="date"
            value={filters.createdTo}
            onChange={(e) => setFilters((prev) => ({ ...prev, createdTo: e.target.value }))}
          />
        </label>
      </form>
      {pageData && (
        <PaginationControls
          page={page}
          pageSize={pageSize}
          total={Number(pageData.total ?? rows.length)}
          count={data.length}
          onPageChange={setPage}
          onPageSizeChange={(size) => { setPageSize(size); setPage(1); }}
          pageSizeOptions={[100, 200, 500]}
          position="top"
        />
      )}
      {showRefreshLoading && (
        <div className="mb-3 flex items-center gap-2 text-xs text-[#6f6857]" role="status" aria-live="polite">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
          <span>{t("common.loading")}</span>
        </div>
      )}
      {error && (
        <div
          className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-[#d9b8ad] bg-[#fff9f6] px-4 py-3 text-sm text-[#6f3024]"
          role="alert"
        >
          <span>{t("page.models.loadError")}</span>
          <button type="button" className="btn" onClick={() => void mutate()}>
            {t("common.retry")}
          </button>
        </div>
      )}
      <div className="grid grid-cols-1 gap-3" aria-busy={showInitialLoading || showRefreshLoading}>
        {showInitialLoading && (
          <div
            className="flex items-center justify-center gap-2 rounded-lg border border-[#ded9ca] bg-[#fdfcf8] p-8 text-sm text-[#6f6857]"
            role="status"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            <span>{t("common.loading")}</span>
          </div>
        )}
        {rows.map((m) => {
          const imageUrl = previewImageUrl(m);
          const modelName = displayModelName(m);
          const codeParts = modelCodeParts(m);
          const variants = Array.isArray(m.variants) ? m.variants : [];
          const modelNo = m.group_model_no || codeParts.modelNo || m.code;
          const variantCount = Number(m.variant_count || variants.length || 1);
          const materialComposition = formatModelComposition(m);
          return (
            <article key={m.id} className="model-list-card overflow-hidden rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] shadow-sm transition hover:border-[#d6ceb9] hover:shadow-md">
              <div className="grid min-h-[128px] grid-cols-[96px_minmax(0,1fr)] items-start sm:grid-cols-[120px_minmax(0,1fr)]">
                <Link href={`${modelPageBase}/${m.id}`} prefetch={false} className="flex min-h-[128px] w-full items-center bg-[#f1efe8]">
                  {imageUrl ? (
                    <VerticalModelPhoto
                      src={imageUrl}
                      alt={modelName}
                      className="w-full border-r border-[#e3dfd3]"
                      loading="lazy"
                      width={240}
                      height={320}
                      adaptiveHeight
                    />
                  ) : (
                    <div className="flex aspect-[3/4] w-full flex-col items-center justify-center gap-2 border-r border-[#e3dfd3] px-3 text-center">
                      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[#ded9ca] bg-[#fdfcf8] text-sm font-semibold text-[#56503f]">
                        {String(codeParts.modelNo || m.code || modelName || "?").slice(0, 2).toUpperCase()}
                      </div>
                      <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-[#8a8472]">{t("page.models.noPreview")}</div>
                    </div>
                  )}
                </Link>
                <div className="grid min-w-0 gap-3 p-3 md:grid-cols-[minmax(220px,0.9fr)_minmax(300px,1.1fr)] xl:grid-cols-[minmax(240px,0.9fr)_minmax(360px,1fr)_minmax(240px,0.8fr)]">
                  <div className="min-w-0">
                    <div className="mono text-xs font-semibold uppercase text-[#8a8472]">{modelNo}</div>
                    <div className="mt-0.5 text-[11px] text-[#8a8472]">{t("page.modelDetail.tab.variants")}: {variantCount}</div>
                    <Link href={`${modelPageBase}/${m.id}`} prefetch={false} className="mt-1 block break-words text-base font-semibold leading-snug text-[#14110b] hover:underline">
                      {modelName}
                    </Link>
                  </div>

                  <div className="min-w-0 xl:pt-1">
                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                      {variants.slice(0, 4).map((variant) => {
                        const option = modelVariantOption(variant);
                        const thumb = variantThumbUrl(variant);
                        return (
                          <Link
                            key={variant.model_id || variant.id}
                            href={`${modelPageBase}/${variant.model_id || variant.id}`}
                            prefetch={false}
                            className="grid grid-cols-[44px_minmax(0,1fr)] gap-2 rounded-md border border-[#ecebe3] bg-white/70 p-2 text-xs hover:border-[#d6ceb9]"
                          >
                            <div className="h-11 w-11 overflow-hidden rounded border border-[#e3dfd3] bg-[#f1efe8]">
                              {thumb ? (
                                <img src={thumb} alt={option.variantNo || option.code} className="h-full w-full object-contain p-1" loading="lazy" />
                              ) : (
                                <div className="flex h-full items-center justify-center text-[10px] text-[#8a8472]">{t("page.models.noPreview")}</div>
                              )}
                            </div>
                            <div className="min-w-0">
                              <div className="truncate font-semibold text-[#14110b]">{option.variantNo || option.code || "-"}</div>
                              <div className="mt-0.5 truncate text-[#56503f]">{option.fabric || "-"}</div>
                            </div>
                          </Link>
                        );
                      })}
                      {variants.length > 4 && (
                        <div className="flex items-center rounded-md border border-dashed border-[#ded9ca] px-3 py-2 text-xs text-[#8a8472]">
                          +{variants.length - 4}
                        </div>
                      )}
                    </div>
                  </div>

                  <dl className="grid grid-cols-1 gap-2 text-xs text-[#56503f] sm:grid-cols-3 xl:pt-5">
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

                  <div className="flex min-w-0 flex-col gap-2 md:col-span-2 xl:col-span-1 xl:items-end">
                    <span className={`badge w-fit shrink-0 ${m.status === "approved" ? "badge-green" : "badge-yellow"}`}>{t(`modelStatus.${m.status}`)}</span>
                    {materialComposition && (
                      <div className="text-xs xl:max-w-[300px] xl:text-right">
                        <div className="label mb-0">{t("field.composition")}</div>
                        <div className="mt-1 break-words text-[#14110b]">{materialComposition}</div>
                      </div>
                    )}

                    <div className="text-sm">
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 xl:justify-end">
                        <Link href={`${modelPageBase}/${m.id}`} prefetch={false} className="font-medium text-brand-600 hover:underline">{t("btn.view")}</Link>
                        {m.status !== "approved" && (
                          <button type="button" className="font-medium text-green-700 hover:underline" onClick={() => approve(m.id)}>{t("btn.approve")}</button>
                        )}
                        {canManage && (
                          <>
                            <button
                              type="button"
                              className="font-medium text-slate-700 hover:underline disabled:opacity-60"
                              onClick={() => cloneModel(m)}
                              disabled={cloningId === m.id}
                            >
                              {cloningId === m.id ? t("page.models.cloning") : t("btn.clone")}
                            </button>
                            <Link href={`${modelPageBase}/${m.id}?mode=edit`} prefetch={false} className="font-medium text-slate-700 hover:underline">{t("btn.edit")}</Link>
                            <button type="button" className="font-medium text-red-600 hover:underline" onClick={() => removeModel(m)}>{t("common.delete")}</button>
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </article>
          );
        })}
        {showEmpty && (
          <div className="rounded-lg border border-dashed border-[#ded9ca] bg-[#fdfcf8] p-8 text-center text-sm text-[#8a8472]">
            {t("page.models.empty")}
          </div>
        )}
      </div>
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
