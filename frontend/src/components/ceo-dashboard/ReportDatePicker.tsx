"use client";

import { useRef, useState } from "react";
import { DayPicker, TZDate, type DateRange as CalendarRange } from "@daypicker/react";
import { enGB, ru, uz } from "@daypicker/react/locale";
import { CalendarDays, ChevronDown, X } from "lucide-react";
import type { Lang } from "@/lib/i18n";
import type { DashboardCopy } from "./messages";
import { businessDate, presetRange, presets, timezone, type DateRange, type Preset } from "./report";
import "@daypicker/react/style.css";
import styles from "./dashboard.module.css";

const locales = { en: enGB, ru, uz };

function calendarDay(day: string) {
  const [year, month, date] = day.split("-").map(Number);
  return new TZDate(year, month - 1, date, 12, timezone);
}

export function ReportDatePicker({ range, preset, today, lang, copy, formatRange, onApply }: {
  range: DateRange;
  preset: Preset;
  today: string;
  lang: Lang;
  copy: DashboardCopy;
  formatRange: (range: DateRange) => string;
  onApply: (range: DateRange, preset: Preset) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<CalendarRange>();
  const [draftPreset, setDraftPreset] = useState<Preset>(preset);
  const [month, setMonth] = useState<Date>(() => calendarDay(range.start));
  const [rangeError, setRangeError] = useState(false);
  const maxDay = calendarDay(today);
  const from = draft?.from && businessDate(draft.from);
  const to = draft?.to && businessDate(draft.to);

  function openCalendar() {
    setDraft({ from: calendarDay(range.start), to: calendarDay(range.end) });
    setDraftPreset(preset);
    setMonth(calendarDay(range.start));
    setRangeError(false);
    setOpen(true);
    dialog.current?.showModal();
  }

  function selectPreset(next: Exclude<Preset, "custom">) {
    const nextRange = presetRange(next, today);
    setDraft({ from: calendarDay(nextRange.start), to: calendarDay(nextRange.end) });
    setDraftPreset(next);
    setMonth(calendarDay(nextRange.start));
    setRangeError(false);
  }

  function selectDays(next: CalendarRange | undefined, clicked: Date) {
    setDraftPreset("custom");
    if (draft?.from && !draft.to && Math.abs(Date.parse(businessDate(clicked)) - Date.parse(businessDate(draft.from))) > 365 * 86_400_000) {
      setRangeError(true);
      return;
    }
    setRangeError(false);
    setDraft(next);
  }

  function apply() {
    if (!from || !to || rangeError || to > today) return;
    onApply({ start: from, end: to }, draftPreset);
    dialog.current?.close();
  }

  return <>
    <button ref={trigger} type="button" className={styles.dateTrigger} aria-haspopup="dialog"
      aria-label={`${copy.period}: ${formatRange(range)}`} onClick={openCalendar}>
      <CalendarDays size={18} aria-hidden="true" />
      <span>{formatRange(range)}</span>
      <ChevronDown size={15} aria-hidden="true" />
    </button>
    <dialog ref={dialog} className={styles.calendarDialog} aria-labelledby="ceo-calendar-title"
      onClose={() => { setOpen(false); trigger.current?.focus(); }}>
      <header className={styles.calendarHeader}>
        <h2 id="ceo-calendar-title">{copy.chooseRange}</h2>
        <button type="button" className={styles.closeCalendar} aria-label={copy.cancel}
          onClick={() => dialog.current?.close()}><X size={20} aria-hidden="true" /></button>
      </header>
      {open && <>
        <div className={styles.calendarBody}>
          <div className={styles.calendarPresets} role="group" aria-label={copy.period}>
            {presets.filter(next => next !== "custom").map(next => <button key={next} type="button"
              aria-pressed={draftPreset === next} onClick={() => selectPreset(next)}>{copy[next]}</button>)}
          </div>
          <DayPicker mode="range" selected={draft} onSelect={selectDays} resetOnSelect required
            timeZone={timezone} today={maxDay} disabled={{ after: maxDay }} endMonth={maxDay}
            month={month} onMonthChange={setMonth} captionLayout="dropdown" navLayout="after"
            locale={locales[lang]} weekStartsOn={1} fixedWeeks autoFocus
            labels={{ labelPrevious: () => copy.previousMonth, labelNext: () => copy.nextMonth,
              labelMonthDropdown: () => copy.monthLabel, labelYearDropdown: () => copy.yearLabel }} />
        </div>
        <footer className={styles.calendarFooter}>
          <p role="status">{rangeError ? copy.dateLimit : from && to ? formatRange({ start: from, end: to }) : copy.pickEndDate}</p>
          <div>
            <button type="button" className={styles.applyButton} onClick={() => dialog.current?.close()}>{copy.cancel}</button>
            <button type="button" className={`${styles.applyButton} ${styles.primaryButton}`}
              disabled={!from || !to || rangeError} onClick={apply}>{copy.apply}</button>
          </div>
        </footer>
      </>}
    </dialog>
  </>;
}
