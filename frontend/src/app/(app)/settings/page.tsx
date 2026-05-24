"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";

import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";

type SettingsPayload = {
  company_info: { name: string; logo_url?: string | null; address?: string | null; phone?: string | null; email?: string | null };
  financial: { default_currency: string; tax_rate_percent: number; fiscal_year_start_month: number };
  preferences: { default_language: string; timezone: string; model_types: string[] };
};

const DEFAULTS: SettingsPayload = {
  company_info: { name: "Milana Ecosystem", logo_url: "", address: "", phone: "", email: "" },
  financial: { default_currency: "USD", tax_rate_percent: 0, fiscal_year_start_month: 1 },
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
    setFinancial({ ...DEFAULTS.financial, ...(data.financial || {}) });
    setPreferences({ ...DEFAULTS.preferences, ...(data.preferences || {}) });
  }, [data]);

  function validate(section: string) {
    const next: Record<string, string> = {};
    if (section === "company_info") {
      if (!company.name.trim()) next.company_name = "Company name is required.";
      if (company.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(company.email)) next.company_email = "Enter a valid email.";
    }
    if (section === "financial") {
      if (!financial.default_currency.trim()) next.currency = "Currency is required.";
      if (financial.tax_rate_percent < 0 || financial.tax_rate_percent > 100) next.tax = "Tax rate must be 0-100.";
      if (financial.fiscal_year_start_month < 1 || financial.fiscal_year_start_month > 12) next.fiscal = "Month must be 1-12.";
    }
    if (section === "preferences") {
      if (!["en", "ru", "uz"].includes(preferences.default_language)) next.lang = "Choose EN, RU, or UZ.";
      if (!preferences.timezone.trim()) next.tz = "Timezone is required.";
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
    setSaved(`${section.replace("_", " ")} saved.`);
    mutate();
  }

  return (
    <div>
      <PageHeader title="Settings" subtitle="Company, finance, and system defaults" />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Section
          title="Company Info"
          footer={<button className="btn btn-primary" onClick={() => save("company_info")}>Save</button>}
        >
          <div><label className="label">Name</label><input className="input" value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} /></div>
          {errors.company_name && <div className="text-xs text-red-600">{errors.company_name}</div>}
          <div><label className="label">Logo</label><input className="input" type="file" accept="image/*" onChange={(e) => setLogoFile(e.target.files?.[0] || null)} /></div>
          {company.logo_url && <img src={company.logo_url} alt="Company logo" className="h-12 w-12 rounded-md border border-[#ecebe3] object-contain" />}
          <div><label className="label">Address</label><input className="input" value={company.address || ""} onChange={(e) => setCompany({ ...company, address: e.target.value })} /></div>
          <div><label className="label">Phone</label><input className="input" value={company.phone || ""} onChange={(e) => setCompany({ ...company, phone: e.target.value })} /></div>
          <div><label className="label">Email</label><input className="input" type="email" value={company.email || ""} onChange={(e) => setCompany({ ...company, email: e.target.value })} /></div>
          {errors.company_email && <div className="text-xs text-red-600">{errors.company_email}</div>}
        </Section>

        <Section
          title="Financial Settings"
          footer={<button className="btn btn-primary" onClick={() => save("financial")}>Save</button>}
        >
          <div><label className="label">Default currency</label><input className="input" value={financial.default_currency} onChange={(e) => setFinancial({ ...financial, default_currency: e.target.value.toUpperCase() })} /></div>
          {errors.currency && <div className="text-xs text-red-600">{errors.currency}</div>}
          <div><label className="label">Tax rate %</label><input className="input" type="number" step="0.01" value={financial.tax_rate_percent} onChange={(e) => setFinancial({ ...financial, tax_rate_percent: Number(e.target.value) })} /></div>
          {errors.tax && <div className="text-xs text-red-600">{errors.tax}</div>}
          <div><label className="label">Fiscal year start month</label><input className="input" type="number" min={1} max={12} value={financial.fiscal_year_start_month} onChange={(e) => setFinancial({ ...financial, fiscal_year_start_month: Number(e.target.value) })} /></div>
          {errors.fiscal && <div className="text-xs text-red-600">{errors.fiscal}</div>}
        </Section>

        <Section
          title="System Preferences"
          footer={<button className="btn btn-primary" onClick={() => save("preferences")}>Save</button>}
        >
          <div>
            <label className="label">Default language</label>
            <select className="input" value={preferences.default_language} onChange={(e) => setPreferences({ ...preferences, default_language: e.target.value })}>
              <option value="en">English</option>
              <option value="ru">Russian</option>
              <option value="uz">Uzbek</option>
            </select>
          </div>
          {errors.lang && <div className="text-xs text-red-600">{errors.lang}</div>}
          <div><label className="label">Timezone</label><input className="input" value={preferences.timezone} onChange={(e) => setPreferences({ ...preferences, timezone: e.target.value })} /></div>
          {errors.tz && <div className="text-xs text-red-600">{errors.tz}</div>}
          <div>
            <label className="label">Model type options</label>
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
