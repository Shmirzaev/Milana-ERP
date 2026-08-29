"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

const HR_TRANSLATIONS = {
  ru: {
    Recruitment: "Подбор персонала",
    "Candidate profiles and hiring workflow for approved staffing positions.": "Профили кандидатов и процесс найма на утвержденные штатные должности.",
    "Search name, phone, PINFL or passport": "Поиск по имени, телефону, ПИНФЛ или паспорту",
    "All stages": "Все этапы",
    "All positions": "Все должности",
    Interview: "Собеседование",
    "View / edit": "Просмотр / изменить",
    "Candidate profile": "Профиль кандидата",
    "Personal details": "Личные данные",
    "Last name": "Фамилия",
    "First name": "Имя",
    "Middle name": "Отчество",
    "Date of birth": "Дата рождения",
    Gender: "Пол",
    "Not specified": "Не указано",
    Male: "Мужской",
    Female: "Женский",
    Other: "Другое",
    Nationality: "Гражданство",
    "Identity documents": "Документы удостоверения личности",
    "Passport / ID number": "Номер паспорта / ID",
    "Issued by": "Кем выдан",
    "Issue date": "Дата выдачи",
    "Expiry date": "Срок действия",
    "Contact and address": "Контакты и адрес",
    Phone: "Телефон",
    Email: "Эл. почта",
    Country: "Страна",
    "Region / city": "Область / город",
    District: "Район",
    Address: "Адрес",
    "Application details": "Данные заявки",
    Department: "Отдел",
    Position: "Должность",
    "Not selected": "Не выбрано",
    "Position not selected": "Должность не выбрана",
    Stage: "Этап",
    "Application date": "Дата заявки",
    "Interview date and time": "Дата и время собеседования",
    Source: "Источник",
    Notes: "Примечания",
    Cancel: "Отмена",
    Saving: "Сохранение",
    "Save candidate": "Сохранить кандидата",
    "Add candidate": "Добавить кандидата",
    "Open candidates": "Открытые кандидаты",
    Interviews: "Собеседования",
    Offers: "Предложения",
    Hired: "Приняты",
    "General application": "Общая заявка",
    applied: "Подано",
    screening: "Отбор",
    interview: "Собеседование",
    offer: "Предложение",
    hired: "Принят",
    rejected: "Отклонен",
  },
  uz: {
    Recruitment: "Ishga qabul",
    "Candidate profiles and hiring workflow for approved staffing positions.": "Tasdiqlangan shtat lavozimlari uchun nomzod profillari va ishga qabul jarayoni.",
    "Search name, phone, PINFL or passport": "Ism, telefon, JShShIR yoki pasport bo‘yicha qidirish",
    "All stages": "Barcha bosqichlar",
    "All positions": "Barcha lavozimlar",
    Interview: "Suhbat",
    "View / edit": "Ko‘rish / tahrirlash",
    "Candidate profile": "Nomzod profili",
    "Personal details": "Shaxsiy ma’lumotlar",
    "Last name": "Familiya",
    "First name": "Ism",
    "Middle name": "Otasining ismi",
    "Date of birth": "Tug‘ilgan sana",
    Gender: "Jinsi",
    "Not specified": "Ko‘rsatilmagan",
    Male: "Erkak",
    Female: "Ayol",
    Other: "Boshqa",
    Nationality: "Fuqaroligi",
    "Identity documents": "Shaxsni tasdiqlovchi hujjatlar",
    "Passport / ID number": "Pasport / ID raqami",
    "Issued by": "Kim tomonidan berilgan",
    "Issue date": "Berilgan sana",
    "Expiry date": "Amal qilish muddati",
    "Contact and address": "Aloqa va manzil",
    Phone: "Telefon",
    Email: "E-pochta",
    Country: "Mamlakat",
    "Region / city": "Viloyat / shahar",
    District: "Tuman",
    Address: "Manzil",
    "Application details": "Ariza ma’lumotlari",
    Department: "Bo‘lim",
    Position: "Lavozim",
    "Not selected": "Tanlanmagan",
    "Position not selected": "Lavozim tanlanmagan",
    Stage: "Bosqich",
    "Application date": "Ariza sanasi",
    "Interview date and time": "Suhbat sanasi va vaqti",
    Source: "Manba",
    Notes: "Izohlar",
    Cancel: "Bekor qilish",
    Saving: "Saqlanmoqda",
    "Save candidate": "Nomzodni saqlash",
    "Add candidate": "Nomzod qo‘shish",
    "Open candidates": "Ochiq nomzodlar",
    Interviews: "Suhbatlar",
    Offers: "Takliflar",
    Hired: "Qabul qilingan",
    "General application": "Umumiy ariza",
    applied: "Ariza berilgan",
    screening: "Saralash",
    interview: "Suhbat",
    offer: "Taklif",
    hired: "Qabul qilingan",
    rejected: "Rad etilgan",
  },
} satisfies Record<"ru" | "uz", Record<string, string>>;

export function useHrT() {
  const { lang } = useT();
  return (key: string) => lang === "en" ? key : HR_TRANSLATIONS[lang]?.[key] ?? key;
}

export function HrHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return <PageHeader title={title} subtitle={subtitle} actions={actions} />;
}

export function MetricGrid({ items }: { items: { label: string; value: ReactNode; hint?: string }[] }) {
  return (
    <div className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div className="card p-4" key={item.label}>
          <div className="text-xs font-semibold uppercase tracking-wide text-[#8a8472]">{item.label}</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums text-[#14110b]">{item.value}</div>
          {item.hint && <div className="mt-1 text-xs text-[#8a8472]">{item.hint}</div>}
        </div>
      ))}
    </div>
  );
}

export function HrWorkspaceNav() {
  const pathname = usePathname() || "/hr";
  const links = [
    ["Dashboard", "/hr"], ["Employees", "/hr/employees"],
    ["Organization Structure", "/hr/organization"], ["Positions & Staffing Plan", "/hr/positions"],
    ["Recruitment", "/hr/recruitment"], ["Employee Documents", "/hr/documents"],
    ["Attendance & Time Tracking", "/hr/attendance"], ["HR Analytics", "/hr/analytics"],
    ["HR Calendar", "/hr/calendar"], ["Settings", "/hr/settings"],
  ];
  return (
    <nav className="card mb-6 overflow-x-auto p-2" aria-label="HR workspace sections">
      <div className="flex min-w-max gap-1">
        {links.map(([label, href]) => {
          const active = href === "/hr" ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
          return <Link className={`rounded-md px-3 py-2 text-sm transition ${active ? "bg-[#14110b] text-white" : "text-[#56503f] hover:bg-[#f1efe8]"}`} href={href} key={href}>{label}</Link>;
        })}
      </div>
    </nav>
  );
}

export function LoadState({ loading, error, empty, children }: { loading?: boolean; error?: unknown; empty?: boolean; children: ReactNode }) {
  if (loading) return <div className="card p-8 text-center text-sm text-[#8a8472]">Loading…</div>;
  if (error) return <div className="card border-red-200 p-5 text-sm text-red-700">Could not load HR data. {String((error as Error)?.message || "")}</div>;
  if (empty) return <div className="card p-8 text-center text-sm text-[#8a8472]">No records yet.</div>;
  return <>{children}</>;
}
