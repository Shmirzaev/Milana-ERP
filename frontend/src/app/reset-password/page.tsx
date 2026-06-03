"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { useT } from "@/lib/i18n";
import BrandLogo from "@/components/BrandLogo";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<ResetShell>{null}</ResetShell>}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function ResetPasswordForm() {
  const { t } = useT();
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState(token ? "" : t("reset.missingToken"));
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setMessage("");
    setLoading(true);
    try {
      await api.resetPassword(token, newPassword, confirmPassword);
      setMessage(t("reset.success"));
      setNewPassword("");
      setConfirmPassword("");
    } catch (err: any) {
      const detail = String(err?.message || "");
      setError(detail.replace(/^\d+:\s*/, "") || t("reset.error"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <ResetShell>
      <h1
        className="m-0 mb-2.5 text-[40px] leading-[1.04]"
        style={{ fontFamily: "'Instrument Serif', 'Iowan Old Style', Palatino, serif", fontWeight: 400 }}
      >
        {t("reset.title")}
      </h1>
      <p className="m-0 mb-7 text-sm text-[#56503f]">{t("reset.subtitle")}</p>

      <form onSubmit={onSubmit} className="flex flex-col gap-4">
        <div>
          <label className="label">{t("reset.newPassword")}</label>
          <input
            className="input"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            required
            disabled={!token || Boolean(message)}
            style={{ height: 42, fontSize: 14 }}
          />
        </div>
        <div>
          <label className="label">{t("reset.confirmPassword")}</label>
          <input
            className="input"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
            required
            disabled={!token || Boolean(message)}
            style={{ height: 42, fontSize: 14 }}
          />
        </div>

        {message && (
          <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-[12.5px] text-green-700">
            {message}
          </div>
        )}
        {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-[12.5px] text-red-700">
            {error}
          </div>
        )}

        {!message && (
          <button
            type="submit"
            disabled={loading || !token}
            className="btn btn-primary w-full justify-center mt-1"
            style={{ height: 44, fontSize: 13.5 }}
          >
            {loading ? t("reset.submitting") : t("reset.submit")}
          </button>
        )}
      </form>

      <Link href="/login" className="mt-5 inline-flex text-[12.5px] font-medium text-[#c2410c] hover:underline">
        {t("reset.backToLogin")}
      </Link>
    </ResetShell>
  );
}

function ResetShell({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen bg-[#f1efe8] px-6 py-10 text-[#14110b]">
      <div className="mx-auto flex min-h-[calc(100vh-80px)] w-full max-w-[420px] flex-col justify-center">
        <div className="mb-8">
          <BrandLogo alt="Milana Ecosystem" className="h-14 w-auto max-w-[240px]" />
        </div>
        <section className="rounded-lg border border-[#e3dfd3] bg-[#fdfcf8] p-6 shadow-sm">
          {children}
        </section>
      </div>
    </main>
  );
}
