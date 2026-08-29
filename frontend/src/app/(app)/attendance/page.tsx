"use client";

import { useDeferredValue, useMemo, useState } from "react";
import useSWR from "swr";
import { Clock3, Download, FileSpreadsheet, Plus, RefreshCw, Search, ShieldCheck, UserCheck, Users } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import PageHeader from "@/components/PageHeader";
import Modal from "@/components/Modal";
import { api, fetcher } from "@/lib/api";
import { can, useMe } from "@/lib/auth";
import { useT } from "@/lib/i18n";

type Device = {
  id: number;
  device_key: string;
  name: string;
  vendor: string;
  model: string | null;
  serial_no: string | null;
  source_host: string | null;
  certificate_sha256: string | null;
  managed: boolean;
  sync_enabled: boolean;
  read_only: boolean;
  reported_person_count: number | null;
  last_seen_at: string | null;
  last_people_sync_at: string | null;
  last_event_sync_at: string | null;
};

type Person = {
  id: number;
  external_person_id: string;
  full_name: string;
  user_type: string | null;
  is_valid: boolean;
  has_face: boolean;
  has_photo: boolean;
  event_count: number;
  arrival_at: string | null;
  departure_at: string | null;
  worked_minutes: number | null;
  attendance_status: "complete" | "single_scan" | "absent";
};

type Overview = {
  date: string;
  summary: {
    total_people: number;
    used_today: number;
    not_used_today: number;
    events_today: number;
    unmatched_events: number;
  };
  devices: Device[];
  people: Person[];
  pagination: { page: number; page_size: number; total: number; pages: number };
};

function todayInTashkent() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

function formatTime(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "Asia/Tashkent",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDateTime(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "Asia/Tashkent",
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(value: number | null) {
  if (value === null) return "—";
  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

function PersonPhoto({ person }: { person: Person }) {
  const [failed, setFailed] = useState(false);
  const initials = person.full_name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join("").toUpperCase();
  if (!person.has_photo || failed) {
    return (
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-[#dedbd0] bg-[#f4f2eb] text-xs font-semibold text-[#6d6757]" aria-hidden="true">
        {initials || "?"}
      </div>
    );
  }
  return (
    // A normal img is intentional: it forwards the signed-in same-origin cookie to the protected endpoint.
    <img
      src={`/api/attendance/people/${person.id}/photo`}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-10 w-10 shrink-0 rounded-md border border-[#dedbd0] object-cover"
    />
  );
}

export default function AttendancePage() {
  const { t, lang } = useT();
  const { me } = useMe();
  const canManageDevices = can(me, "attendance.manage", "*");
  const [day, setDay] = useState(todayInTashkent);
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim());
  const [usage, setUsage] = useState("all");
  const [page, setPage] = useState(1);
  const [downloadingReport, setDownloadingReport] = useState(false);
  const [reportError, setReportError] = useState("");
  const [deviceOpen, setDeviceOpen] = useState(false);
  const [deviceBusy, setDeviceBusy] = useState(false);
  const [deviceError, setDeviceError] = useState("");
  const [deviceForm, setDeviceForm] = useState({
    device_key: "",
    name: "",
    vendor: "Dahua",
    source_host: "https://",
    certificate_sha256: "",
    username: "",
    password: "",
  });
  const endpoint = useMemo(() => {
    const params = new URLSearchParams({ day, usage, page: String(page), page_size: "50" });
    if (deferredQuery) params.set("query", deferredQuery);
    return `/api/attendance/overview?${params.toString()}`;
  }, [day, usage, page, deferredQuery]);
  const { data, error, isLoading, isValidating, mutate } = useSWR<Overview>(endpoint, fetcher, { refreshInterval: 60_000 });
  const devices = data?.devices ?? [];
  const lastEventSyncAt = devices.reduce<string | null>((latest, device) => {
    if (!device.last_event_sync_at) return latest;
    if (!latest || new Date(device.last_event_sync_at) > new Date(latest)) return device.last_event_sync_at;
    return latest;
  }, null);
  const metrics: Array<{ label: string; value: number | string; icon: LucideIcon }> = [
    { label: t("attendance.totalProfiles"), value: data?.summary.total_people ?? "—", icon: Users },
    { label: t("attendance.usedTurnstile"), value: data?.summary.used_today ?? "—", icon: UserCheck },
    { label: t("attendance.notUsed"), value: data?.summary.not_used_today ?? "—", icon: Clock3 },
    { label: t("attendance.scans"), value: data?.summary.events_today ?? "—", icon: ShieldCheck },
  ];

  function updateFilter(change: () => void) {
    setPage(1);
    change();
  }

  async function downloadDailyReport() {
    setDownloadingReport(true);
    setReportError("");
    try {
      const params = new URLSearchParams({ day, usage, lang });
      if (deferredQuery) params.set("query", deferredQuery);
      const response = await fetch(`/api/attendance/reports/daily.xlsx?${params.toString()}`, {
        credentials: "same-origin",
      });
      if (!response.ok) {
        let detail = response.statusText;
        try {
          const body = await response.json();
          detail = body.detail || detail;
        } catch {}
        throw new Error(`${response.status}: ${detail}`);
      }
      const disposition = response.headers.get("content-disposition") || "";
      const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]
        || `attendance_daily_${day}.xlsx`;
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch (downloadError: any) {
      setReportError(downloadError?.message || t("attendance.reportDownloadFailed"));
    } finally {
      setDownloadingReport(false);
    }
  }

  function statusLabel(person: Person) {
    if (person.attendance_status === "complete") return t("attendance.completeDay");
    if (person.attendance_status === "single_scan") return t("attendance.singleScan");
    return t("attendance.absent");
  }

  function downloadJson(fileName: string, payload: Record<string, unknown>) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = fileName;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  async function addManagedDevice() {
    setDeviceBusy(true);
    setDeviceError("");
    try {
      const created = await api.post<Device & { connector_token: string }>("/api/attendance/devices", {
        device_key: deviceForm.device_key,
        name: deviceForm.name,
        vendor: deviceForm.vendor,
        source_host: deviceForm.source_host,
        certificate_sha256: deviceForm.certificate_sha256,
      });
      const config = {
        vendor: deviceForm.vendor,
        device_key: created.device_key,
        device_name: created.name,
        erp_base_url: window.location.origin,
        hikvision_base_url: deviceForm.vendor === "Hikvision" ? deviceForm.source_host : undefined,
        dahua_base_url: deviceForm.vendor === "Dahua" ? deviceForm.source_host : undefined,
        device_cert_sha256: deviceForm.certificate_sha256,
        hikvision_cert_sha256: deviceForm.vendor === "Hikvision" ? deviceForm.certificate_sha256 : undefined,
        initial_event_days: 30,
        people_sync_hours: 24,
        sync_photos: true,
      };
      const secrets = {
        vendor: deviceForm.vendor,
        device_username: deviceForm.username,
        device_password: deviceForm.password,
        hikvision_username: deviceForm.vendor === "Hikvision" ? deviceForm.username : undefined,
        hikvision_password: deviceForm.vendor === "Hikvision" ? deviceForm.password : undefined,
        erp_token: created.connector_token,
      };
      downloadJson(`${created.device_key}.attendance.json`, config);
      downloadJson(`${created.device_key}.attendance.secrets.json`, secrets);
      setDeviceForm({ device_key: "", name: "", vendor: "Dahua", source_host: "https://", certificate_sha256: "", username: "", password: "" });
      setDeviceOpen(false);
      await mutate();
    } catch (submitError: unknown) {
      setDeviceError(String((submitError as Error)?.message || submitError));
    } finally {
      setDeviceBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        title={t("page.attendance.title")}
        subtitle={t("page.attendance.subtitle")}
        actions={(
          <div className="flex flex-wrap items-center gap-2">
            {canManageDevices && (
              <button className="btn inline-flex items-center gap-2" onClick={() => { setDeviceError(""); setDeviceOpen(true); }}>
                <Plus className="h-4 w-4" />{t("attendance.addDevice")}
              </button>
            )}
            <button className="btn btn-primary inline-flex items-center gap-2" onClick={() => void downloadDailyReport()} disabled={downloadingReport}>
              <FileSpreadsheet className="h-4 w-4" />
              {downloadingReport ? t("common.loading") : t("attendance.excelReport")}
            </button>
            <button className="btn inline-flex items-center gap-2" onClick={() => void mutate()} disabled={isValidating}>
              <RefreshCw className={`h-4 w-4 ${isValidating ? "animate-spin" : ""}`} />
              {t("common.refresh")}
            </button>
          </div>
        )}
      />

      <div className="mb-5 border-y border-[#dedbd0] bg-[#fbfaf6]">
        <dl className="grid grid-cols-2 divide-x divide-y divide-[#dedbd0] sm:grid-cols-4 sm:divide-y-0">
          {metrics.map(({ label, value, icon: Icon }) => (
            <div key={label} className="flex items-center gap-3 px-4 py-3">
              <Icon className="h-4 w-4 shrink-0 text-[#8a8472]" />
              <div>
                <dt className="text-xs text-[#8a8472]">{label}</dt>
                <dd className="mt-0.5 text-xl font-semibold tabular-nums text-[#14110b]">{value}</dd>
              </div>
            </div>
          ))}
        </dl>
      </div>

      <div className="card mb-5 p-4">
        <div className="grid gap-3 md:grid-cols-[minmax(220px,1fr)_170px_190px]">
          <label>
            <span className="label">{t("common.search")}</span>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#8a8472]" />
              <input
                className="input pl-9"
                value={query}
                onChange={(event) => updateFilter(() => setQuery(event.target.value))}
                placeholder={t("attendance.searchPlaceholder")}
              />
            </div>
          </label>
          <label>
            <span className="label">{t("attendance.usage")}</span>
            <select className="input" value={usage} onChange={(event) => updateFilter(() => setUsage(event.target.value))}>
              <option value="all">{t("common.all")}</option>
              <option value="used">{t("attendance.used")}</option>
              <option value="not_used">{t("attendance.notUsed")}</option>
            </select>
          </label>
          <label>
            <span className="label">{t("attendance.date")}</span>
            <input className="input" type="date" value={day} onChange={(event) => updateFilter(() => setDay(event.target.value))} />
          </label>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-[#ecebe3] pt-3 text-xs text-[#6d6757]">
          <span className="font-medium text-[#353126]">
            {devices.length ? t("attendance.devicesConnected", { count: devices.length }) : t("attendance.awaitingDevice")}
          </span>
          {devices.length > 0 && devices.every((device) => device.read_only) && (
            <span className="inline-flex items-center gap-1"><ShieldCheck className="h-3.5 w-3.5" />{t("attendance.readOnly")}</span>
          )}
          <span>{t("attendance.deviceProfiles")}: {data?.summary.total_people ?? "—"}</span>
          <span>{t("attendance.lastEventSync")}: {formatDateTime(lastEventSyncAt)}</span>
        </div>
      </div>

      <div className="card overflow-hidden">
        {reportError && <div className="border-b border-[#ecebe3] p-4 text-sm text-red-700">{reportError}</div>}
        {error && <div className="border-b border-[#ecebe3] p-4 text-sm text-red-700">{t("attendance.loadError")}</div>}
        <div className="overflow-x-auto">
          <table className="table min-w-[780px]">
            <thead>
              <tr>
                <th>{t("attendance.employee")}</th>
                <th>{t("attendance.employeeId")}</th>
                <th>{t("attendance.dailyStatus")}</th>
                <th>{t("attendance.arrival")}</th>
                <th>{t("attendance.departure")}</th>
                <th className="text-right">{t("attendance.timeBetweenScans")}</th>
              </tr>
            </thead>
            <tbody>
              {isLoading && !data && <tr><td colSpan={6} className="p-6 text-center text-sm text-[#8a8472]">{t("common.loading")}</td></tr>}
              {!isLoading && data?.people.length === 0 && <tr><td colSpan={6} className="p-8 text-center text-sm text-[#8a8472]">{t("attendance.empty")}</td></tr>}
              {data?.people.map((person) => (
                <tr key={person.id}>
                  <td>
                    <div className="flex items-center gap-3">
                      <PersonPhoto person={person} />
                      <div className="min-w-0">
                        <div className="font-medium text-[#242117]">{person.full_name}</div>
                        <div className="mt-0.5 text-xs text-[#8a8472]">{person.is_valid ? t("attendance.validProfile") : t("attendance.invalidProfile")}</div>
                      </div>
                    </div>
                  </td>
                  <td className="font-mono text-xs">{person.external_person_id}</td>
                  <td>
                    <span className={person.attendance_status === "complete" ? "text-emerald-700" : person.attendance_status === "single_scan" ? "text-amber-700" : "text-[#8a8472]"}>
                      {statusLabel(person)}
                    </span>
                  </td>
                  <td className="tabular-nums">{formatTime(person.arrival_at)}</td>
                  <td className="tabular-nums">{formatTime(person.departure_at)}</td>
                  <td className="text-right font-medium tabular-nums">{formatDuration(person.worked_minutes)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data && data.pagination.pages > 1 && (
          <div className="flex items-center justify-between border-t border-[#ecebe3] px-4 py-3 text-sm">
            <span className="text-[#8a8472]">{t("attendance.resultCount", { count: data.pagination.total })}</span>
            <div className="flex items-center gap-2">
              <button className="btn" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>{t("common.previous")}</button>
              <span className="min-w-20 text-center tabular-nums">{page} / {data.pagination.pages}</span>
              <button className="btn" disabled={page >= data.pagination.pages} onClick={() => setPage((value) => value + 1)}>{t("common.next")}</button>
            </div>
          </div>
        )}
      </div>

      <Modal open={deviceOpen} onClose={() => setDeviceOpen(false)} title={t("attendance.addDevice")}>
        <div className="mb-4 border border-[#dedbd0] bg-[#fbfaf6] px-3 py-2 text-sm text-[#56503f]">
          {t("attendance.deviceSetupHint")}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label><span className="label">{t("attendance.vendor")}</span><select className="input" value={deviceForm.vendor} onChange={(event) => setDeviceForm({ ...deviceForm, vendor: event.target.value })}><option value="Dahua">Dahua</option><option value="Hikvision">Hikvision</option></select></label>
          <label><span className="label">{t("attendance.deviceKey")}</span><input className="input" value={deviceForm.device_key} onChange={(event) => setDeviceForm({ ...deviceForm, device_key: event.target.value })} placeholder="ect-main-gate" /></label>
          <label><span className="label">{t("attendance.deviceName")}</span><input className="input" value={deviceForm.name} onChange={(event) => setDeviceForm({ ...deviceForm, name: event.target.value })} /></label>
          <label><span className="label">{t("attendance.deviceUrl")}</span><input className="input" type="url" value={deviceForm.source_host} onChange={(event) => setDeviceForm({ ...deviceForm, source_host: event.target.value })} placeholder="https://10.0.0.20" /></label>
          <label className="sm:col-span-2"><span className="label">{t("attendance.certificateFingerprint")}</span><input className="input font-mono text-xs" value={deviceForm.certificate_sha256} onChange={(event) => setDeviceForm({ ...deviceForm, certificate_sha256: event.target.value })} /></label>
          <label><span className="label">{t("attendance.deviceUsername")}</span><input className="input" autoComplete="username" value={deviceForm.username} onChange={(event) => setDeviceForm({ ...deviceForm, username: event.target.value })} /></label>
          <label><span className="label">{t("attendance.devicePassword")}</span><input className="input" type="password" autoComplete="new-password" value={deviceForm.password} onChange={(event) => setDeviceForm({ ...deviceForm, password: event.target.value })} /></label>
        </div>
        <div className="mt-3 text-xs text-[#6d6757]">{t("attendance.passwordLocalOnly")}</div>
        {deviceError && <div className="mt-3 text-sm text-red-700">{deviceError}</div>}
        <div className="mt-4 flex justify-end gap-2">
          <button className="btn" onClick={() => setDeviceOpen(false)}>{t("btn.cancel")}</button>
          <button className="btn btn-primary inline-flex items-center gap-2" onClick={() => void addManagedDevice()} disabled={deviceBusy}>
            <Download className="h-4 w-4" />{deviceBusy ? t("common.saving") : t("attendance.saveAndDownload")}
          </button>
        </div>
      </Modal>
    </div>
  );
}
