"use client";
import { useState } from "react";
import useSWR from "swr";
import { api, fetcher } from "@/lib/api";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function DepartmentsPage() {
  const { t } = useT();
  const { data, mutate } = useSWR<any[]>("/api/departments", fetcher);
  const [f, setF] = useState({ name: "", code: "" });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    await api.post("/api/departments", f);
    setF({ name: "", code: "" });
    mutate();
  }

  return (
    <div>
      <PageHeader title={t("page.admin.depts")} />
      <form onSubmit={submit} className="card mb-6 grid grid-cols-3 gap-3 p-4">
        <input
          className="input"
          placeholder={t("common.name")}
          value={f.name}
          onChange={(e) => setF({ ...f, name: e.target.value })}
          required
        />
        <input
          className="input"
          placeholder={t("common.code")}
          value={f.code}
          onChange={(e) => setF({ ...f, code: e.target.value })}
          required
        />
        <button className="btn btn-primary">{t("btn.add")}</button>
      </form>
      <div className="card">
        <table className="table">
          <thead>
            <tr>
              <th>{t("common.code")}</th>
              <th>{t("common.name")}</th>
            </tr>
          </thead>
          <tbody>{data?.map((d) => <tr key={d.id}><td>{d.code}</td><td>{d.name}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
