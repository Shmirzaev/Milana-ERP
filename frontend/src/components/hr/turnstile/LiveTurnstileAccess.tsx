"use client";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import Modal from "@/components/Modal";
import { api, fetcher } from "@/lib/api";
import { ApiError } from "@/lib/errorMessages";
import { useT } from "@/lib/i18n";
import { uploadPhoto } from "./turnstileBackend";
import { type GateEmployee } from "./turnstilePreview";
import { LiveAction, LiveState, PhysicalUserType, livePrefix, lookupLive, submitLive, validLiveRequest, type LiveContext, type LivePayload, type PendingLiveRequest } from "./turnstileLive";
import { liveCopy } from "./turnstileLiveCopy";

export default function LiveTurnstileAccess({ employee, actorId, onClose }: { employee: GateEmployee; actorId: number; onClose: () => void }) {
  const { lang } = useT(); const c = liveCopy[lang];
  const { data, error, isLoading, mutate } = useSWR<LiveContext>(`${livePrefix}/employees/${employee.id}`, fetcher, { refreshInterval: 2500 });
  const [deviceId, setDeviceId] = useState(0), [action, setAction] = useState(LiveAction.Observe);
  const [name, setName] = useState(employee.full_name), [photoId, setPhotoId] = useState<number | null>(null);
  const [preview, setPreview] = useState(""), [confirmation, setConfirmation] = useState(""), [adoptConfirmation, setAdoptConfirmation] = useState("");
  const [busy, setBusy] = useState(false), [message, setMessage] = useState(""), [pending, setPending] = useState<PendingLiveRequest | null>(null);
  const [recoveryBlocked, setRecoveryBlocked] = useState(false); const uploadGeneration = useRef(0);
  const inFlight = useRef(false);
  function beginOperation() { if (inFlight.current) return false; inFlight.current = true; setBusy(true); return true; }
  function endOperation() { inFlight.current = false; setBusy(false); }
  const journalKey = `turnstile-live:v1:${actorId}:${employee.factory_code}:${employee.id}`;
  const device = data?.devices.find(d => d.id === deviceId), profile = data?.profiles.find(p => p.device_id === deviceId);
  const observation = data?.jobs.find(j => j.device_id === deviceId && j.action === LiveAction.Observe && j.state === LiveState.Succeeded);
  const number = data?.employee_no || "";
  const reviewKey = JSON.stringify([deviceId, action, number, profile?.profile_hash, name.trim(), photoId]);
  const adoptKey = JSON.stringify([observation?.id, observation?.profile_hash, number]);
  const needsPhoto = action === LiveAction.Enroll || action === LiveAction.Photo;
  const needsName = action === LiveAction.Enroll || action === LiveAction.Edit;
  const needsBaseline = ![LiveAction.Observe, LiveAction.Enroll].includes(action);
  const canSubmit = !!data?.enabled && !!device?.identity_allowed && !!number && !busy && !pending && !recoveryBlocked
    && (action === LiveAction.Observe || (device.writes_enabled && confirmation === reviewKey
      && (!needsPhoto || !!photoId) && (!needsName || !!name.trim()) && (!needsBaseline || !!profile?.profile_hash)));

  useEffect(() => {
    try {
      const stored = sessionStorage.getItem(journalKey);
      if (stored) { const value: unknown = JSON.parse(stored); if (!validLiveRequest(value)) throw new Error("Invalid saved request"); setPending(value); }
    } catch { setRecoveryBlocked(true); }
  }, [journalKey]);
  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview); }, [preview]);
  useEffect(() => () => { uploadGeneration.current++; }, []);

  function clearOwnRequest(key: string) {
    const stored: unknown = JSON.parse(sessionStorage.getItem(journalKey) || "null");
    if (validLiveRequest(stored) && stored.key === key) sessionStorage.removeItem(journalKey);
  }
  async function send(request: PendingLiveRequest, acquired = false) {
    if (!acquired && !beginOperation()) return;
    try {
      await submitLive(employee.id, request);
      clearOwnRequest(request.key); setPending(null); setMessage(c.waiting); await mutate();
    } catch (e) {
      if (e instanceof ApiError && [400, 401, 403, 404, 409, 413, 415, 422].includes(e.status)) {
        // A refusal to replay does not prove an earlier timed-out submission
        // was never accepted. Reconcile its scoped receipt before discarding.
        try {
          const accepted = await lookupLive(employee.id, request.key);
          clearOwnRequest(request.key); setPending(null); setMessage(accepted ? c.waiting : c.refused); await mutate();
        } catch { setPending(request); setMessage(c.unknown); }
      } else { setPending(request); setMessage(c.unknown); }
    } finally { endOperation(); }
  }
  async function submit() {
    if (!canSubmit || !beginOperation()) return;
    const payload: LivePayload = { expected_employee_no: number, device_id: deviceId, action };
    if (needsName) payload.reviewed_name = name.trim();
    if (needsPhoto && photoId) { payload.photo_asset_id = photoId; payload.manual_face_reviewed = true; }
    if (needsBaseline && profile?.profile_hash) payload.expected_profile_hash = profile.profile_hash;
    if (action === LiveAction.Delete) payload.delete_credentials_confirmed = true;
    const request = { key: crypto.randomUUID(), payload };
    try { sessionStorage.setItem(journalKey, JSON.stringify(request)); }
    catch { setRecoveryBlocked(true); setMessage(c.unknown); endOperation(); return; }
    setPending(request); setConfirmation(""); await send(request, true);
  }
  async function checkReceipt() {
    if (!pending || !beginOperation()) return;
    try {
      const job = await lookupLive(employee.id, pending.key);
      if (job) { clearOwnRequest(pending.key); setPending(null); setMessage(c.waiting); await mutate(); }
      else setMessage(c.unknown);
    } catch { setMessage(c.unknown); } finally { endOperation(); }
  }
  async function adopt() {
    if (!observation?.profile_hash || adoptConfirmation !== adoptKey || !beginOperation()) return;
    try {
      await api.post(`${livePrefix}/employees/${employee.id}/adopt`, { expected_employee_no: number,
        observation_job_id: observation.id, expected_profile_hash: observation.profile_hash, identity_reviewed: true });
      setAdoptConfirmation(""); setMessage(c.adopted); await mutate();
    } catch { setMessage(c.refused); } finally { endOperation(); }
  }
  async function retryUnsent(jobId: number) {
    if (pending || recoveryBlocked || !beginOperation()) return;
    try { await api.post(`${livePrefix}/jobs/${jobId}/retry-unsent`, {}); setMessage(c.waiting); await mutate(); }
    catch { setMessage(c.refused); } finally { endOperation(); }
  }
  async function upload(file: File | undefined) {
    if (!beginOperation()) return;
    const generation = ++uploadGeneration.current; setPhotoId(null); setConfirmation("");
    if (!file) { setPreview(""); endOperation(); return; }
    setPreview(URL.createObjectURL(file));
    try { const photo = await uploadPhoto(employee.id, file); if (generation === uploadGeneration.current) setPhotoId(photo.id); }
    catch { if (generation === uploadGeneration.current) setMessage(c.refused); }
    finally { endOperation(); }
  }
  return <Modal open onClose={onClose} title={`${c.title} · ${employee.full_name}`} wide closeOnOutsideClick={false}>
    <div className="space-y-4">
      <p className="text-sm text-[var(--erp-text-muted)]">{c.help}</p>
      {isLoading && <p role="status">{c.loading}</p>}
      {error && <p role="alert">{c.error}</p>}
      {data && !data.enabled && <p role="status">{c.disabled}</p>}
      {data?.enabled && !data.devices.length && <p role="status">{c.empty}</p>}
      {data?.enabled && <>
        <label className="block text-sm">{c.number}<input className="input mt-1 w-full" value={number} readOnly /></label>
        {!number && <p role="alert">{c.identityMissing}</p>}
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block text-sm">{c.terminal}<select className="input mt-1 w-full" value={deviceId || ""} disabled={busy || !!pending} onChange={e => setDeviceId(Number(e.target.value))}>
            <option value="">{c.select}</option>{data.devices.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select></label>
          <label className="block text-sm">{c.action}<select className="input mt-1 w-full" value={action} disabled={busy || !!pending} onChange={e => setAction(e.target.value as LiveAction)}>
            {Object.values(LiveAction).map(a => <option key={a} value={a}>{c.actions[a]}</option>)}
          </select></label>
        </div>
        {device && !device.writes_enabled && <p className="text-sm" role="status">{c.handover}</p>}
        {profile?.snapshot?.present && <section className="border-t pt-3 text-sm"><h3 className="font-semibold">{c.profile}</h3>
          <p>{profile.snapshot.full_name} · {profile.snapshot.external_person_id}</p>
          <p>{profile.snapshot.user_type === PhysicalUserType.Blocked ? c.blocked : profile.snapshot.user_type === PhysicalUserType.Visitor ? c.visitor : c.active}</p>
          <p>{profile.snapshot.policy?.validity.begin} – {profile.snapshot.policy?.validity.end}</p>
        </section>}
        {observation?.observation && <section className="space-y-2 border-t pt-3 text-sm"><h3 className="font-semibold">{c.observation}</h3>
          {observation.observation.present ? <>
            <p>{observation.observation.full_name} · {observation.observation.external_person_id}</p>
            <p>{new Date(observation.created_at).toLocaleString(lang)}</p>
            <label className="flex items-start gap-2"><input type="checkbox" checked={adoptConfirmation === adoptKey} disabled={busy || !!pending} onChange={e => setAdoptConfirmation(e.target.checked ? adoptKey : "")} />{c.adoptReview}</label>
            <button type="button" className="btn btn-secondary" disabled={busy || !!pending || adoptConfirmation !== adoptKey} onClick={() => void adopt()}>{c.adopt}</button>
          </> : <p>{c.absent}</p>}
        </section>}
        {needsBaseline && !profile?.profile_hash && <p className="text-sm">{c.noProfile}</p>}
        {needsName && <label className="block text-sm">{c.name}<input className="input mt-1 w-full" value={name} maxLength={255} disabled={busy || !!pending} onChange={e => setName(e.target.value)} /></label>}
        {needsPhoto && <label className="block text-sm">{c.upload}<input className="mt-1 block w-full" type="file" accept="image/jpeg,image/png" disabled={busy || !!pending} onChange={e => void upload(e.target.files?.[0])} />
          {/* Private local selection, never sent to a public image service. */}
          {preview && <img src={preview} alt={c.upload} className="mt-2 h-36 w-28 rounded-md border object-contain" />}
        </label>}
        {action === LiveAction.Revoke && <p className="text-sm">{c.revoke}</p>}
        {action === LiveAction.Delete && <p className="text-sm text-red-700">{c.deletion}</p>}
        {action !== LiveAction.Observe && <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={confirmation === reviewKey} disabled={busy || !!pending} onChange={e => setConfirmation(e.target.checked ? reviewKey : "")} />{c.review}</label>}
        <button type="button" className="btn btn-primary" disabled={!canSubmit} onClick={() => void submit()}>{c.apply}</button>
      </>}
      {(message || pending || recoveryBlocked) && <p role="status" className="text-sm">{pending || recoveryBlocked ? c.unknown : message}</p>}
      {pending && <div className="flex flex-wrap gap-2"><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void checkReceipt()}>{c.receipt}</button>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void send(pending)}>{c.retrySaved}</button></div>}
      <div className="flex items-center justify-between gap-3 border-t pt-3"><h3 className="font-semibold">{c.history}</h3><button type="button" className="btn btn-secondary" disabled={busy} onClick={() => void mutate()}>{c.refresh}</button></div>
      {!data?.jobs.length && <p className="text-sm">{c.noHistory}</p>}
      <ul className="divide-y">{data?.jobs.map(job => <li key={job.id} className="flex flex-wrap justify-between gap-2 py-2 text-sm">
        <span>{c.actions[job.action]} · {data.devices.find(d => d.id === job.device_id)?.name || c.terminal}<br />{new Date(job.created_at).toLocaleString(lang)}</span>
        <span>{c.states[job.state]}{job.state === LiveState.Failed && <button type="button" className="btn btn-secondary ml-2" disabled={busy || !!pending || recoveryBlocked} onClick={() => void retryUnsent(job.id)}>{c.retryUnsent}</button>}</span>
      </li>)}</ul>
    </div>
  </Modal>;
}
