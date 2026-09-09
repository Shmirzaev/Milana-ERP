"use client";

import { useEffect, useRef, useState } from "react";
import SearchableSelect from "@/components/SearchableSelect";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";

export type PayrollSearchEmployee = {
  type: "employee_payroll";
  employee_id: number;
  employee_name: string;
  employee_no?: string | null;
  department_name?: string | null;
  position?: string | null;
};

const messages = {
  en: { label: "Find employee by name", placeholder: "Type a name or employee number", start: "Type at least 2 characters", empty: "No active employees found", loading: "Searching…", more: "More matches available. Type more of the name.", error: "Employee search failed. Try typing again." },
  ru: { label: "Найти сотрудника по имени", placeholder: "Введите имя или табельный номер", start: "Введите минимум 2 символа", empty: "Активные сотрудники не найдены", loading: "Поиск…", more: "Есть ещё совпадения. Уточните имя.", error: "Не удалось найти сотрудников. Повторите ввод." },
  uz: { label: "Xodimni ismi bo‘yicha qidirish", placeholder: "Ism yoki xodim raqamini kiriting", start: "Kamida 2 ta belgi kiriting", empty: "Faol xodimlar topilmadi", loading: "Qidirilmoqda…", more: "Yana mos xodimlar bor. Ismni to‘liqroq kiriting.", error: "Xodimlarni qidirib bo‘lmadi. Qayta kiriting." },
};

export default function PayrollEmployeeSearch({ onSelect }: {
  onSelect: (employee: PayrollSearchEmployee) => void;
}) {
  const { lang } = useT();
  const text = messages[lang];
  const [query, setQuery] = useState("");
  const [items, setItems] = useState<PayrollSearchEmployee[]>([]);
  const [loading, setLoading] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [failed, setFailed] = useState(false);
  const requestVersion = useRef(0);

  useEffect(() => {
    const version = ++requestVersion.current;
    if (query.trim().length < 2) return;
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await api.get<{ items: PayrollSearchEmployee[]; has_more: boolean }>(
          `/api/payroll/employees/search?q=${encodeURIComponent(query.trim())}`,
        );
        if (cancelled || version !== requestVersion.current) return;
        setItems(result.items);
        setHasMore(result.has_more);
      } catch {
        if (!cancelled && version === requestVersion.current) setFailed(true);
      } finally {
        if (!cancelled && version === requestVersion.current) setLoading(false);
      }
    }, 200);
    return () => { window.clearTimeout(timer); cancelled = true; };
  }, [query]);

  return (
    <div className="mt-4" data-payroll-employee-search>
      <label className="label" htmlFor="payroll-employee-search">{text.label}</label>
      <SearchableSelect<number>
        inputId="payroll-employee-search"
        value={null}
        options={items.map(employee => ({
          value: employee.employee_id,
          label: employee.employee_name,
          metaText: [employee.employee_no, employee.department_name, employee.position].filter(Boolean).join(" · "),
        }))}
        serverFilter
        loading={loading}
        loadingText={text.loading}
        placeholder={text.placeholder}
        noResultsText={query.trim().length < 2 ? text.start : failed ? text.error : text.empty}
        onSearchChange={value => {
          requestVersion.current++;
          setItems([]);
          setHasMore(false);
          setFailed(false);
          setLoading(value.trim().length >= 2);
          setQuery(value);
        }}
        onChange={id => {
          const employee = items.find(item => item.employee_id === id);
          if (!employee) return;
          requestVersion.current++;
          setQuery("");
          setItems([]);
          setHasMore(false);
          setLoading(false);
          // Run after the combobox's own focus handling so the next QR is ready.
          window.queueMicrotask(() => onSelect(employee));
        }}
      />
      {hasMore && <p className="mt-1 text-xs text-[#8a8472]" role="status">{text.more}</p>}
    </div>
  );
}
