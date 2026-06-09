"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { useMe } from "@/lib/auth";
import PageHeader from "@/components/PageHeader";
import { useT } from "@/lib/i18n";

export default function ProfilePage() {
  const { me, refresh } = useMe();
  const { t } = useT();
  const [profile, setProfile] = useState({ name: "", email: "" });
  const [password, setPassword] = useState({ current_password: "", new_password: "", confirm_new_password: "" });
  const [profileMsg, setProfileMsg] = useState("");
  const [passwordMsg, setPasswordMsg] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!me) return;
    setProfile({ name: me.name || "", email: me.email || "" });
  }, [me]);

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    setProfileMsg("");
    const next: Record<string, string> = {};
    if (!profile.name.trim()) next.name = t("page.profile.nameRequired");
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(profile.email)) next.email = t("page.profile.validEmail");
    setErrors(next);
    if (Object.keys(next).length) return;
    try {
      await api.patch("/api/auth/me", profile);
      await refresh();
      setProfileMsg(t("page.profile.saved"));
    } catch (err: any) {
      setProfileMsg(err.message);
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    setPasswordMsg("");
    if (password.new_password !== password.confirm_new_password) {
      setErrors({ password: t("page.profile.passwordsNoMatch") });
      return;
    }
    setErrors({});
    try {
      await api.post("/api/auth/change-password", password);
      setPassword({ current_password: "", new_password: "", confirm_new_password: "" });
      setPasswordMsg(t("page.profile.passwordUpdated"));
    } catch (err: any) {
      setPasswordMsg(err.message);
    }
  }

  return (
    <div>
      <PageHeader title={t("page.profile.title")} subtitle={t("page.profile.subtitle")} />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <form onSubmit={saveProfile} className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[#56503f]">{t("page.profile.userProfile")}</h2>
          <div><label className="label">{t("common.name")}</label><input className="input" value={profile.name} onChange={(e) => setProfile({ ...profile, name: e.target.value })} /></div>
          {errors.name && <div className="text-xs text-red-600">{errors.name}</div>}
          <div><label className="label">{t("field.email")}</label><input className="input" type="email" value={profile.email} onChange={(e) => setProfile({ ...profile, email: e.target.value })} /></div>
          {errors.email && <div className="text-xs text-red-600">{errors.email}</div>}
          <div className="grid grid-cols-2 gap-3">
            <div><label className="label">{t("field.role")}</label><input className="input" value={me?.role || "-"} readOnly /></div>
            <div><label className="label">{t("field.department")}</label><input className="input" value={me?.department || "-"} readOnly /></div>
          </div>
          {profileMsg && <div className={`text-sm ${profileMsg.includes(":") ? "text-red-600" : "text-green-700"}`}>{profileMsg}</div>}
          <div className="flex justify-end"><button className="btn btn-primary">{t("common.save")}</button></div>
        </form>

        <form onSubmit={changePassword} className="card p-4 space-y-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[#56503f]">{t("page.profile.changePassword")}</h2>
          <div><label className="label">{t("field.currentPassword")}</label><input className="input" type="password" value={password.current_password} onChange={(e) => setPassword({ ...password, current_password: e.target.value })} required /></div>
          <div><label className="label">{t("reset.newPassword")}</label><input className="input" type="password" value={password.new_password} onChange={(e) => setPassword({ ...password, new_password: e.target.value })} required /></div>
          <div><label className="label">{t("reset.confirmPassword")}</label><input className="input" type="password" value={password.confirm_new_password} onChange={(e) => setPassword({ ...password, confirm_new_password: e.target.value })} required /></div>
          {errors.password && <div className="text-xs text-red-600">{errors.password}</div>}
          {passwordMsg && <div className={`text-sm ${passwordMsg.includes(":") || passwordMsg.toLowerCase().includes("incorrect") ? "text-red-600" : "text-green-700"}`}>{passwordMsg}</div>}
          <div className="flex justify-end"><button className="btn btn-primary">{t("page.profile.savePassword")}</button></div>
        </form>
      </div>
    </div>
  );
}
