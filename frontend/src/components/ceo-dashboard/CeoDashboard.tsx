"use client";

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Clock3, RefreshCw, SlidersHorizontal } from "lucide-react";
import { fetchResponse } from "@/lib/api";
import { isCeo, useMe } from "@/lib/auth";
import { ApiError } from "@/lib/errorMessages";
import { useT } from "@/lib/i18n";
import { messages } from "./messages";
import {
  businessDate, factories, groupings, presetRange, timezone,
  type CeoReport, type DateRange, type Factory, type Grouping, type Preset,
} from "./report";
import { Activity, Balances, HandoffSummary, type ReportFormatting } from "./ReportSections";
import { ReportDatePicker } from "./ReportDatePicker";
import styles from "./dashboard.module.css";

const refreshInterval = 30_000;

function Segmented<T extends string>({ label, options, chosen, onChange, children }: {
  label: string;
  options: readonly T[];
  chosen: T;
  onChange: (option: T) => void;
  children: (option: T) => ReactNode;
}) {
  return <fieldset className={styles.field}>
    <legend>{label}</legend>
    <div className={styles.segments}>
      {options.map(option => <label key={option}>
        <input type="radio" name={label} value={option} checked={chosen === option} onChange={() => onChange(option)} />
        <span>{children(option)}</span>
      </label>)}
    </div>
  </fieldset>;
}

function useCeoReport(url: string, refreshIdentity: () => Promise<unknown>) {
  const [result, setResult] = useState<{ url: string; data?: CeoReport; error?: unknown }>();
  const [pendingUrl, setPendingUrl] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  const content = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    if (result?.url === url && document.visibilityState === "visible" && content.current) {
      content.current.style.visibility = "";
    }
  }, [result, url]);

  useEffect(() => {
    let active = true;
    let suspended = document.visibilityState !== "visible";
    let request: AbortController | undefined;
    let timer: number | undefined;

    const schedule = () => {
      window.clearTimeout(timer);
      if (active && !suspended) timer = window.setTimeout(() => {
        if (document.visibilityState === "visible") void load();
        else schedule();
      }, refreshInterval);
    };

    async function load() {
      if (!active || suspended || request) return;
      window.clearTimeout(timer);
      const controller = new AbortController();
      request = controller;
      setPendingUrl(url);
      const deadline = window.setTimeout(() => controller.abort(), 12_000);
      let allowRetry = true;
      try {
        const response = await fetchResponse(url, {
          cache: "no-store",
          credentials: "same-origin",
          signal: controller.signal,
        });
        if (!response.ok) throw new ApiError(response.status, response.statusText);
        const data: CeoReport = await response.json();
        if (active && !controller.signal.aborted) setResult({ url, data });
      } catch (error) {
        if (!active || request !== controller) return;
        const denied = error instanceof ApiError && (error.status === 401 || error.status === 403);
        allowRetry = !denied;
        setResult({ url, error });
        if (denied) void refreshIdentity().catch(() => undefined);
      } finally {
        window.clearTimeout(deadline);
        if (active && request === controller) {
          request = undefined;
          setPendingUrl(undefined);
          if (allowRetry) schedule();
        }
      }
    }

    const hide = () => {
      suspended = true;
      window.clearTimeout(timer);
      request?.abort();
      request = undefined;
      // Keep history snapshots and restored tabs free of stale report content.
      if (content.current) content.current.style.visibility = "hidden";
      setResult(undefined);
    };
    const restore = () => {
      if (!suspended || document.visibilityState !== "visible") return;
      suspended = false;
      void load();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") restore();
      else hide();
    };

    window.addEventListener("pagehide", hide);
    window.addEventListener("pageshow", restore);
    document.addEventListener("visibilitychange", onVisibility);
    void load();
    return () => {
      active = false;
      window.clearTimeout(timer);
      request?.abort();
      window.removeEventListener("pagehide", hide);
      window.removeEventListener("pageshow", restore);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [url, refresh, refreshIdentity]);

  return {
    data: result?.url === url ? result.data : undefined,
    error: result?.url === url ? result.error : undefined,
    pending: pendingUrl === url,
    refresh: () => setRefresh(value => value + 1),
    content,
  };
}

export default function CeoDashboard() {
  const { me, refresh } = useMe();
  return me && isCeo(me) ? <DashboardView key={me.id} refreshIdentity={refresh} /> : null;
}

function DashboardView({ refreshIdentity }: { refreshIdentity: () => Promise<unknown> }) {
  const { lang } = useT();
  const copy = messages[lang];
  const [today, setToday] = useState(businessDate);
  const [preset, setPreset] = useState<Preset>("today");
  const [factory, setFactory] = useState<Factory>("ALL");
  const [grouping, setGrouping] = useState<Grouping>("daily");
  const [customRange, setCustomRange] = useState<DateRange>({ start: today, end: today });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [balanceSelection, setBalanceSelection] = useState<{ reportKey: string; end: string }>();
  const range = preset === "custom" ? customRange : presetRange(preset, today);
  const url = `/api/dashboard/ceo?${new URLSearchParams({ ...range, grouping, factory })}`;
  const { data, error, pending, refresh, content } = useCeoReport(url, refreshIdentity);
  const denied = error instanceof ApiError && (error.status === 401 || error.status === 403);
  const balanceKey = `${range.end}/${grouping}`;
  const chosenBalance = (balanceSelection?.reportKey === balanceKey
    ? data?.balances.find(point => point.end === balanceSelection.end)
    : undefined) ?? data?.balances.at(-1);

  useEffect(() => {
    const clock = () => setToday(businessDate());
    const timer = window.setInterval(clock, 15_000);
    window.addEventListener("pageshow", clock);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("pageshow", clock);
    };
  }, []);

  const locale = { en: "en-GB", ru: "ru-RU", uz: "uz-Latn-UZ" }[lang];
  const number = new Intl.NumberFormat(locale, { maximumFractionDigits: 6 });
  const month = lang === "uz" ? "2-digit" : "short";
  const date = new Intl.DateTimeFormat(locale, { day: "numeric", month, year: "numeric", timeZone: "UTC" });
  const axisDate = new Intl.DateTimeFormat(locale, { day: "numeric", month, timeZone: "UTC" });
  const time = new Intl.DateTimeFormat(locale, { hour: "2-digit", minute: "2-digit", second: "2-digit", timeZone: timezone });
  const timestamp = new Intl.DateTimeFormat(locale, lang === "uz"
    ? { day: "numeric", month, year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: timezone }
    : { dateStyle: "medium", timeStyle: "short", timeZone: timezone });
  const dateAt = (value: string) => new Date(`${value}T12:00:00Z`);
  const format: ReportFormatting = {
    count: value => number.format(Number(value)),
    range: ({ start, end }) => start === end ? date.format(dateAt(start)) : date.formatRange(dateAt(start), dateAt(end)),
    axis: value => axisDate.format(dateAt(value)),
    timestamp: value => timestamp.format(new Date(value)),
    duration: minutes => {
      const days = Math.floor(minutes / 1440);
      const hours = Math.floor(minutes / 60) % 24;
      const unit = (value: number, name: "day" | "hour" | "minute") =>
        new Intl.NumberFormat(locale, { style: "unit", unit: name, unitDisplay: "short" }).format(value);
      if (days) return hours ? `${unit(days, "day")} ${unit(hours, "hour")}` : unit(days, "day");
      const remainder = minutes % 60;
      if (hours) return remainder ? `${unit(hours, "hour")} ${unit(remainder, "minute")}` : unit(hours, "hour");
      return minutes ? unit(minutes, "minute") : copy.underMinute;
    },
  };

  return <div className={styles.dashboard}>
    <header className={styles.pageHeader}>
      <h1>{copy.title}</h1>
      <div className={styles.refreshStatus}>
        <div className={styles.refreshText}>
          <span><Clock3 size={14} aria-hidden="true" />{copy.businessTime} <span className={styles.utc}>(UTC+5)</span></span>
          {data && <span>{copy.updated} <time dateTime={data.updated_at} title={format.timestamp(data.updated_at)}>{time.format(new Date(data.updated_at))}</time></span>}
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh} disabled={pending}
          aria-label={pending ? copy.refreshing : copy.refresh} title={pending ? copy.refreshing : copy.refresh}>
          <RefreshCw size={17} className={pending ? styles.spinning : undefined} aria-hidden="true" />
        </button>
      </div>
    </header>

    <div className={styles.controlBar}>
      <div className={styles.dateControl}>
        <ReportDatePicker range={range} preset={preset} today={today} lang={lang} copy={copy} formatRange={format.range}
          onApply={(next, nextPreset) => { setCustomRange(next); setPreset(nextPreset); }} />
      </div>
      <div className={styles.filterSummary}>
        <span>{copy[factory]} · {copy[grouping]}</span>
        <button type="button" className={styles.filterButton} aria-expanded={filtersOpen} aria-controls="ceo-report-filters"
          onClick={() => setFiltersOpen(open => !open)}>
          <SlidersHorizontal size={16} aria-hidden="true" />{copy.filters}
        </button>
      </div>
      <div id="ceo-report-filters" className={styles.controls} data-open={filtersOpen}>
        <Segmented<Grouping> label={copy.grouping} options={groupings} chosen={grouping} onChange={setGrouping}>{option => copy[option]}</Segmented>
        <Segmented<Factory> label={copy.factory} options={factories} chosen={factory} onChange={setFactory}>{option => copy[option]}</Segmented>
      </div>
    </div>

    <div ref={content} className={styles.report}>
      {!data && !error && <div className={styles.state} role="status">{copy.loading}</div>}
      {error ? <div className={styles.state} role="alert">
        <p>{denied ? copy.denied : copy.error}</p>
        {!denied && <button type="button" className={styles.applyButton} onClick={refresh} disabled={pending}>{copy.retry}</button>}
      </div> : null}
      {data && <>
        {chosenBalance && <HandoffSummary point={chosenBalance} copy={copy} format={format} />}
        <Activity key={`${data.start}/${data.end}/${data.grouping}`} report={data} copy={copy} format={format} />
        {chosenBalance && <Balances balances={data.balances} chosen={chosenBalance}
          onDateChange={end => setBalanceSelection({ reportKey: balanceKey, end })}
          factory={data.factory} copy={copy} format={format} />}
      </>}
    </div>
  </div>;
}
