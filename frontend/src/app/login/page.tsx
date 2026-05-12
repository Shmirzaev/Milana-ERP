"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import LangSwitcher from "@/components/LangSwitcher";

export default function LoginPage() {
  const router = useRouter();
  const { t } = useT();
  const [email, setEmail] = useState("admin@example.com");
  const [password, setPassword] = useState("admin12345");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(email, password);
      // Hard navigation so the (app) layout remounts and re-reads localStorage cleanly.
      window.location.href = "/";
    } catch (err: any) {
      setError(err.message || t("auth.loginFailed"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100 px-4">
      <div className="card w-full max-w-sm p-6">
        <div className="flex justify-end mb-2"><LangSwitcher /></div>
        <h1 className="text-2xl font-bold mb-1 text-slate-900">{t("app.name")}</h1>
        <p className="text-sm text-slate-500 mb-6">{t("app.tagline")}</p>
        <form onSubmit={onSubmit} className="space-y-4">
          <div>
            <label className="label">{t("auth.email")}</label>
            <input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>
          <div>
            <label className="label">{t("auth.password")}</label>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          {error && <div className="text-sm text-red-600">{error}</div>}
          <button type="submit" className="btn btn-primary w-full justify-center" disabled={loading}>
            {loading ? t("auth.signingIn") : t("auth.signIn")}
          </button>
        </form>
        <div className="text-xs text-slate-500 mt-5">
          {t("auth.defaultAdmin")}: <code>admin@example.com</code> / <code>admin12345</code>
        </div>
      </div>
    </div>
  );
}
