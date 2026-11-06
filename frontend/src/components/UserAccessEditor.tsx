"use client";

import { useEffect, useId, useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useMe } from "@/lib/auth";
import { accessText, changeAccess, type AccessPolicy, type AccessSubject, type FactoryCode } from "@/lib/userAccess";

type Permission = { key: string; group: string; label: Record<string, string>; grantable: boolean };
type Preview = Record<FactoryCode, { effective: string[]; available: boolean }>;

const factories: Record<FactoryCode, string> = { MIL: "Milana", BST: "Besttex", ECO: "Eco Cotton" };

export default function UserAccessEditor({ subject, value, onChange, onReady }: {
  subject: AccessSubject;
  value: AccessPolicy | null;
  onChange: (value: AccessPolicy) => void;
  onReady: (ready: boolean) => void;
}) {
  const { lang } = useT();
  const editorId = useId();
  const { me } = useMe();
  const copy = accessText(lang);
  const [factory, setFactory] = useState<FactoryCode>(subject.factory_code);
  const [search, setSearch] = useState("");
  const { data: catalog, error: catalogError } = useSWR<Permission[]>("/api/access-catalog", fetcher);
  const payload = JSON.stringify({ name: subject.name || "Preview", email: subject.email || "preview@example.com",
    role_id: subject.role_id, department_id: subject.department_id, factory_code: subject.factory_code,
    extra_permissions: subject.extra_permissions ?? [], access_policy: value });
  const [settled, setSettled] = useState(payload);
  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(payload), 180);
    return () => window.clearTimeout(timer);
  }, [payload]);
  const { data: preview, error: previewError, isLoading } = useSWR<Preview>(
    ["user-access-preview", settled], () => api.post("/api/users/access-preview", JSON.parse(settled)),
    { keepPreviousData: true },
  );
  const ready = Boolean(catalog && preview && !catalogError && !previewError && !isLoading && payload === settled);
  useEffect(() => { onReady(ready); }, [ready, onReady]);
  const policy = value?.[factory];
  const canEditFactory = Boolean(me?.permissions.includes("admin.super") || factory === me?.factory_code);
  const query = search.trim().toLocaleLowerCase();
  const groups = [...new Set((catalog ?? []).map((p) => p.group))];
  const changed = (policy?.allow.length ?? 0) + (policy?.deny.length ?? 0);
  return (
    <section className="space-y-3 border-t border-[#e3dfd3] pt-3">
      <h3 className="text-sm font-semibold">{copy.title}</h3>
      <p className="text-sm text-[#6f6858]">{copy.help}</p>
      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-40 flex-1 text-sm">
          {copy.factory}
          <select className="input mt-1" value={factory} onChange={(e) => setFactory(e.target.value as FactoryCode)}>
            {Object.entries(factories).map(([code, name]) => <option key={code} value={code}>{name}{code === subject.factory_code ? ` (${copy.primary})` : ""}</option>)}
          </select>
        </label>
        <label className="min-w-48 flex-1 text-sm">
          {copy.search}
          <input className="input mt-1" type="search" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
      </div>
      <p className="text-sm" aria-live="polite">
        {ready ? `${preview?.[factory]?.available ? copy.factoryAvailable : copy.factoryUnavailable} · ${changed} ${copy.overrides}` : copy.loading}
      </p>
      {!canEditFactory && <p className="text-sm text-[#6f6858]">{copy.superOnly}</p>}
      {(catalogError || previewError) && <p role="alert" className="text-sm text-red-700">{copy.loadError}</p>}
      <div className="max-h-[28rem] overflow-y-auto">
        {groups.map((group) => {
          const rows = (catalog ?? []).filter((p) => p.group === group && `${p.label[lang]} ${p.label.en} ${p.key}`.toLocaleLowerCase().includes(query));
          if (!rows.length) return null;
          return <fieldset key={group} className="mb-3">
            <legend className="mb-1 text-sm font-semibold">{copy.groups[group] ?? group}</legend>
            <div className="grid grid-cols-1 gap-x-4 sm:grid-cols-2">
              {rows.map((permission) => {
                const allowed = Boolean(preview?.[factory]?.available && preview?.[factory]?.effective.includes(permission.key));
                const disabled = !ready || !canEditFactory || (!allowed && !permission.grantable)
                  || (permission.key === "admin.super" && factory !== subject.factory_code);
                return <label key={permission.key} htmlFor={`${editorId}-${factory}-${permission.key}`}
                  className={`flex min-h-9 items-center gap-2 py-1 text-sm ${disabled ? "text-[#6f6858]" : "cursor-pointer"}`}>
                  <input id={`${editorId}-${factory}-${permission.key}`} type="checkbox" className="h-4 w-4 shrink-0 accent-[#17140e]"
                    checked={allowed} disabled={disabled}
                    onChange={(e) => onChange(changeAccess(value, factory, permission.key, e.target.checked ? "allow" : "deny"))} />
                  <span>{permission.label[lang] ?? permission.label.en}</span>
                </label>;
              })}
            </div>
          </fieldset>;
        })}
        {catalog && !catalog.some((p) => `${p.label[lang]} ${p.label.en} ${p.key}`.toLocaleLowerCase().includes(query)) && <p className="py-3 text-sm">{copy.noResults}</p>}
      </div>
      <p className="text-xs text-[#6f6858]">{copy.scopeHelp}</p>
    </section>
  );
}
