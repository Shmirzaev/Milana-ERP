"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

type SettingsPayload = {
  company_info: { name: string; logo_url?: string | null; address?: string | null; phone?: string | null; email?: string | null };
  financial: { default_currency: string; fiscal_year_start_month: number };
  preferences: { default_language: string; timezone: string; model_types: string[] };
};

const DEFAULTS: SettingsPayload = {
  company_info: { name: "Milana Ecosystem", logo_url: "", address: "", phone: "", email: "" },
  financial: { default_currency: "USD", fiscal_year_start_month: 1 },
  preferences: { default_language: "en", timezone: "UTC", model_types: ["Dress", "Top", "Skirt", "Pants", "Outerwear"] },
};

function Section({ title, children, footer }: { title: string; children: React.ReactNode; footer: React.ReactNode }) {
  return (
    <section className="card p-4">
      <h2 className="mb-4 text-sm font-semibold uppercase tracking-wide text-[#56503f]">{title}</h2>
      <div className="space-y-3">{children}</div>
      <div className="mt-4 flex items-center justify-end gap-2 border-t border-[#ecebe3] pt-3">{footer}</div>
    </section>
  );
}

export default function SettingsPage() {
  const { t } = useT();
  const { data, mutate } = useSWR<SettingsPayload>("/api/settings", fetcher);
  const [company, setCompany] = useState(DEFAULTS.company_info);
  const [financial, setFinancial] = useState(DEFAULTS.financial);
  const [preferences, setPreferences] = useState(DEFAULTS.preferences);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState("");
  const [logoFile, setLogoFile] = useState<File | null>(null);

  useEffect(() => {
    if (!data) return;
    setCompany({ ...DEFAULTS.company_info, ...(data.company_info || {}) });
    setFinancial({
      default_currency: data.financial?.default_currency || DEFAULTS.financial.default_currency,
      fiscal_year_start_month: Number(data.financial?.fiscal_year_start_month || DEFAULTS.financial.fiscal_year_start_month),
    });
    setPreferences({ ...DEFAULTS.preferences, ...(data.preferences || {}) });
  }, [data]);

  function validate(section: string) {
    const next: Record<string, string> = {};
    if (section === "company_info") {
      if (!company.name.trim()) next.company_name = t("page.settings.companyNameRequired");
      if (company.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(company.email)) next.company_email = t("page.settings.validEmail");
    }
    if (section === "financial") {
      if (!financial.default_currency.trim()) next.currency = t("page.settings.currencyRequired");
      if (financial.fiscal_year_start_month < 1 || financial.fiscal_year_start_month > 12) next.fiscal = t("page.settings.monthRange");
    }
    if (section === "preferences") {
      if (!["en", "ru", "uz"].includes(preferences.default_language)) next.lang = t("page.settings.chooseLanguage");
      if (!preferences.timezone.trim()) next.tz = t("page.settings.timezoneRequired");
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function uploadLogoIfNeeded() {
    if (!logoFile) return company.logo_url || null;
    const form = new FormData();
    form.append("file", logoFile);
    const uploaded = await api.postForm<{ logo_url: string }>("/api/settings/company-logo/upload", form);
    setLogoFile(null);
    return uploaded.logo_url;
  }

  async function save(section: keyof SettingsPayload) {
    setSaved("");
    if (!validate(section)) return;
    const payload =
      section === "company_info"
        ? { ...company, logo_url: await uploadLogoIfNeeded() }
        : section === "financial"
          ? financial
          : preferences;
    await api.patch(`/api/settings/${section}`, payload);
    setSaved(t("page.settings.sectionSaved", { section: t(
      section === "company_info"
        ? "page.settings.companyInfo"
        : section === "financial"
          ? "page.settings.financialSettings"
          : "page.settings.systemPreferences",
    ) }));
    mutate();
  }

  return (
    <div>
      <PageHeader title={t("page.settings.title")} subtitle={t("page.settings.subtitle")} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section
          title={t("page.settings.companyInfo")}
          footer={<button className="btn btn-primary" onClick={() => save("company_info")}>{t("common.save")}</button>}
        >
          <div><label className="label">{t("common.name")}</label><input className="input" value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} /></div>
          {errors.company_name && <div className="text-xs text-red-600">{errors.company_name}</div>}
          <div><label className="label">{t("field.logo")}</label><input className="input" type="file" accept="image/png,image/jpeg,image/webp,image/gif" onChange={(e) => setLogoFile(e.target.files?.[0] || null)} /></div>
          {company.logo_url && <img src={company.logo_url} alt={t("page.settings.companyLogo")} className="h-12 w-12 rounded-md border border-[#ecebe3] object-contain" />}
          <div><label className="label">{t("field.address")}</label><input className="input" value={company.address || ""} onChange={(e) => setCompany({ ...company, address: e.target.value })} /></div>
          <div><label className="label">{t("field.phone")}</label><input className="input" value={company.phone || ""} onChange={(e) => setCompany({ ...company, phone: e.target.value })} /></div>
          <div><label className="label">{t("field.email")}</label><input className="input" type="email" value={company.email || ""} onChange={(e) => setCompany({ ...company, email: e.target.value })} /></div>
          {errors.company_email && <div className="text-xs text-red-600">{errors.company_email}</div>}
        </Section>

        <Section
          title={t("page.settings.financialSettings")}
          footer={<button className="btn btn-primary" onClick={() => save("financial")}>{t("common.save")}</button>}
        >
          <div><label className="label">{t("field.defaultCurrency")}</label><input className="input" value={financial.default_currency} onChange={(e) => setFinancial({ ...financial, default_currency: e.target.value.toUpperCase() })} /></div>
          {errors.currency && <div className="text-xs text-red-600">{errors.currency}</div>}
          <div><label className="label">{t("field.fiscalYearStartMonth")}</label><input className="input" type="number" min={1} max={12} value={financial.fiscal_year_start_month} onChange={(e) => setFinancial({ ...financial, fiscal_year_start_month: Number(e.target.value) })} /></div>
          {errors.fiscal && <div className="text-xs text-red-600">{errors.fiscal}</div>}
        </Section>

        <Section
          title={t("page.settings.systemPreferences")}
          footer={<button className="btn btn-primary" onClick={() => save("preferences")}>{t("common.save")}</button>}
        >
          <div>
            <label className="label">{t("field.defaultLanguage")}</label>
            <select className="input" value={preferences.default_language} onChange={(e) => setPreferences({ ...preferences, default_language: e.target.value })}>
              <option value="en">{t("language.en")}</option>
              <option value="ru">{t("language.ru")}</option>
              <option value="uz">{t("language.uz")}</option>
            </select>
          </div>
          {errors.lang && <div className="text-xs text-red-600">{errors.lang}</div>}
          <div><label className="label">{t("field.timezone")}</label><input className="input" value={preferences.timezone} onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })} /></div>
          {errors.tz && <div className="text-xs text-red-600">{errors.tz}</div>}
          <div>
            <label className="label">{t("field.modelTypeOptions")}</label>
            <textarea
              className="input min-h-24"
              value={preferences.model_types.join("\n")}
              onChange={(e) => setPreferences({ ...preferences, model_types: e.target.value.split("\n").map((v) => v.trim()).filter(Boolean) })}
            />
          </div>
        </Section>
      </div>
      {saved && <div className="mt-4 text-sm text-green-700">{saved}</div>}
    </div>
  );
}
