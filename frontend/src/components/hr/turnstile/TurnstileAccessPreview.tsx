"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ArrowRight, Camera, Check, CheckCircle2, Clock3, DoorOpen, ImagePlus, ShieldCheck, ShieldOff, Upload, X } from "lucide-react";
import Modal from "@/components/Modal";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { GateAction, GateState, PREVIEW_ENABLED, BACKEND_ENABLED, previewKey, readPreview, simulateOperation, type GateDevice, type GateEmployee, type GateOperation } from "./turnstilePreview";
import { backendCopy } from "./turnstileBackendCopy";
import { contextUrl, submitEnrollment, findAcceptedOperation, removeMatchingJournal, markJournalAccepted, getOperation, processOperation, reconnectOperation, projectOperation, uploadPhoto, type EnrollmentPayload, type EnrollmentRequest, type GateContext, type ServerOperation } from "./turnstileBackend";
import { gateCopy } from "./turnstilePreviewCopy";
import styles from "./TurnstileAccessPreview.module.css";

interface Props { employee: GateEmployee; actorId: number; canManage: boolean; onClose: () => void }
interface Photo { url: string; blob: Blob; width: number; height: number }

export default function TurnstileAccessPreview(props: Props) {
  // The wrapper prevents even a read request when this development-only preview is disabled.
  return PREVIEW_ENABLED || BACKEND_ENABLED ? <Preview key={`${props.actorId}:${props.employee.factory_code}:${props.employee.id}`} {...props} /> : null;
}

function Preview({ employee, actorId, canManage, onClose }: Props) {
  const { lang } = useT(); const c = gateCopy[lang]; const b = backendCopy[lang];
  const { data, error, isLoading, mutate } = useSWR<{ devices: GateDevice[] }>(BACKEND_ENABLED ? null : "/api/attendance/overview?page_size=10", fetcher);
  const context = useSWR<GateContext>(BACKEND_ENABLED && canManage ? contextUrl(employee.id) : null, fetcher);
  const devices: GateDevice[] = BACKEND_ENABLED ? (context.data?.devices || []).map(d => ({ ...d, vendor: "Simulator", last_seen_at: null })) : data?.devices || [];
  const deviceError = BACKEND_ENABLED ? context.error : error;
  const deviceLoading = BACKEND_ENABLED ? context.isLoading : isLoading;
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<EnrollmentRequest | null>(null)
  const [accepted, setAccepted] = useState<ServerOperation | null>(null);
  const [action, setAction] = useState(GateAction.Enroll);
  const [name, setName] = useState(employee.full_name);
  const [selected, setSelected] = useState<number[]>([]);
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [checks, setChecks] = useState([false, false]);
  const [message, setMessage] = useState(""); const [storageError, setStorageError] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [reviewedNumber, setReviewedNumber] = useState<string | null>(null);
  const [history, setHistory] = useState<GateOperation[]>([]);
  const [resultId, setResultId] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const video = useRef<HTMLVideoElement>(null); const stream = useRef<MediaStream | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const cameraGeneration = useRef(0); const photoGeneration = useRef(0); const mounted = useRef(true);
  const file = useRef<HTMLInputElement>(null); const photoUrl = useRef<string | null>(null);
  const key = previewKey(actorId, employee);
  const recoveryKey = `turnstile-submit:v1:${actorId}:${employee.factory_code}:${employee.id}`;
  const [recoveryBlocked, setRecoveryBlocked] = useState(false);
  const running = useRef(false);
  const needsPhoto = action === GateAction.Enroll || action === GateAction.Photo;
  const serverOperations = context.data?.operations || [];
  const visibleOperations = accepted && !serverOperations.some(op => op.id === accepted.id) ? [accepted, ...serverOperations] : serverOperations;
  const displayedHistory = BACKEND_ENABLED ? visibleOperations.map(op => projectOperation(op)) : history;
  const latest = displayedHistory.find(item => item.id === resultId) || displayedHistory[0];
  const waiting = latest?.targets.some(t => t.state === GateState.Waiting);
  const employeeNumber = BACKEND_ENABLED ? context.data?.employee_no : employee.employee_no;
  const targetDevices = devices.filter(d => selected.includes(d.id));
  const blocked = !canManage || (BACKEND_ENABLED && (!context.data?.simulator_enabled || busy || !!pending || recoveryBlocked)) || !employeeNumber?.trim() || (employee.status === "archived" && action !== GateAction.Revoke);
  const actionLabel = (value: GateAction) => ({ [GateAction.Enroll]: c.enroll, [GateAction.Edit]: c.edit, [GateAction.Photo]: c.photo, [GateAction.Revoke]: c.revoke })[value];
  const stateLabel = (value: GateState) => ({ [GateState.Verified]: c.verified, [GateState.Waiting]: BACKEND_ENABLED ? b.waiting : c.waiting, [GateState.Revoked]: c.revoked, [GateState.Superseded]: BACKEND_ENABLED ? b.superseded : c.superseded, [GateState.Queued]: b.queued, [GateState.Processing]: b.processing, [GateState.Verifying]: b.verifying, [GateState.Succeeded]: b.succeeded, [GateState.Failed]: b.failedState, [GateState.Conflict]: b.conflict, [GateState.Uncertain]: b.uncertainState, [GateState.Cancelled]: b.cancelled })[value];

  useEffect(() => {
    if (BACKEND_ENABLED && confirm && reviewedNumber !== employeeNumber) { setConfirm(false); setMessage(b.identityChanged); }
  }, [confirm, reviewedNumber, employeeNumber, b.identityChanged]);
  useEffect(() => {
    if (!BACKEND_ENABLED) { setHistory(readPreview(key)); return; }
    try {
      const raw = sessionStorage.getItem(recoveryKey);
      if (!raw) return;
      const saved: unknown = JSON.parse(raw);
      if (!saved || typeof saved !== "object") throw new Error("Invalid recovery request");
      const request = saved as { key?: unknown; payload?: Partial<EnrollmentPayload>; acceptedId?: unknown };
      if (typeof request.key !== "string" || !request.payload || !Array.isArray(request.payload.device_ids) || !request.payload.device_ids.every(x => Number.isInteger(x) && x > 0) || !Number.isInteger(request.payload.photo_asset_id) || typeof request.payload.expected_employee_no !== "string" || !request.payload.expected_employee_no.trim() || request.payload.expected_employee_no.length > 64 || typeof request.payload.reviewed_name !== "string" || request.payload.manual_face_reviewed !== true || request.payload.action !== GateAction.Enroll || (request.acceptedId !== undefined && (!Number.isInteger(request.acceptedId) || Number(request.acceptedId) <= 0))) throw new Error("Invalid recovery request");
      setPending(request as EnrollmentRequest); setMessage(b.uncertain);
    } catch { setRecoveryBlocked(true); setMessage(b.failed); }
  }, [key, recoveryKey, b.uncertain, b.failed]);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.current?.focus({ preventScroll: true });
    const containTab = (event: KeyboardEvent) => {
      if (event.key === "Tab" && !event.defaultPrevented && dialog.current && !dialog.current.contains(document.activeElement)) {
        event.preventDefault(); dialog.current.querySelector<HTMLElement>('button:not(:disabled),input:not(:disabled):not([hidden])')?.focus();
      }
    };
    document.addEventListener("keydown", containTab);
    return () => { document.removeEventListener("keydown", containTab); previous?.focus(); };
  }, []);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      stream.current?.getTracks().forEach(t => t.stop());
      if (photoUrl.current) URL.revokeObjectURL(photoUrl.current);
    };
  }, []);
  useEffect(() => { if (camera && video.current && stream.current) video.current.srcObject = stream.current; }, [camera]);

  function focusWithin(selector: string) { requestAnimationFrame(() => { if (mounted.current) (dialog.current?.querySelector<HTMLElement>(selector) || dialog.current)?.focus(); }); }
  function closeCamera() { cameraGeneration.current++; stream.current?.getTracks().forEach(t => t.stop()); stream.current = null; setCamera(false); focusWithin("[data-gate-upload]"); }
  async function openCamera() {
    closeCamera(); const generation = cameraGeneration.current;
    try {
      const media = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false });
      if (!mounted.current || generation !== cameraGeneration.current) { media.getTracks().forEach(t => t.stop()); return; }
      stream.current = media; setCamera(true); setMessage("");
    } catch { if (mounted.current && generation === cameraGeneration.current) setMessage(c.cameraError); }
  }
  async function selectPhoto(blob: Blob) {
    const generation = ++photoGeneration.current;
    if (!["image/jpeg", "image/png"].includes(blob.type) || blob.size > 8 * 1024 * 1024 || !blob.size) { setMessage(c.photoError); return; }
    const url = URL.createObjectURL(blob);
    try {
      const image = new Image(); image.src = url; await image.decode();
      if (!mounted.current || generation !== photoGeneration.current) { URL.revokeObjectURL(url); return; }
      if (!image.naturalWidth || !image.naturalHeight) throw new Error("Empty image");
      if (photoUrl.current) URL.revokeObjectURL(photoUrl.current);
      photoUrl.current = url; setPhoto({ url, blob, width: image.naturalWidth, height: image.naturalHeight }); setChecks([false, false]); setMessage(""); closeCamera();
    } catch { URL.revokeObjectURL(url); if (mounted.current && generation === photoGeneration.current) setMessage(c.photoError); }
  }
  function capture() {
    if (!video.current?.videoWidth) return;
    const generation = cameraGeneration.current; const selection = photoGeneration.current;
    const canvas = document.createElement("canvas"); canvas.width = video.current.videoWidth; canvas.height = video.current.videoHeight;
    canvas.getContext("2d")?.drawImage(video.current, 0, 0);
    canvas.toBlob(blob => { if (blob && mounted.current && generation === cameraGeneration.current && selection === photoGeneration.current) void selectPhoto(blob); }, "image/jpeg", 0.92);
  }
  function changeAction(next: GateAction) { photoGeneration.current++; closeCamera(); setAction(next); setConfirm(false); setMessage(""); }
  function review() {
    if (blocked) return;
    if (!targetDevices.length) { setMessage(c.selectRequired); return; }
    if (needsPhoto && (!photo || !checks.every(Boolean))) { setMessage(c.photoRequired); return; }
    if (!name.trim()) return;
    setReviewedNumber(employeeNumber || null); setMessage(""); setConfirm(true); focusWithin("[data-gate-confirm]");
  }
  function saveHistory(next: GateOperation[]) {
    setHistory(next);
    try { sessionStorage.setItem(key, JSON.stringify(next)); setStorageError(false); } catch { setStorageError(true); }
  }
  function clearPending(requestKey: string) {
    try { if (removeMatchingJournal(sessionStorage, recoveryKey, requestKey)) setPending(null); else setRecoveryBlocked(true); } catch { setRecoveryBlocked(true); }
  }
  async function retryPending(request: EnrollmentRequest, verifyFirst = false) {
    if (running.current) return;
    running.current = true; setBusy(true); setMessage("");
    try {
      if (verifyFirst) {
        const refreshed = await context.mutate();
        if (!refreshed) { if (mounted.current) setMessage(b.uncertain); return; }
        const existing = findAcceptedOperation(refreshed.operations, request);
        if (existing) {
          if (mounted.current) { setAccepted(existing); setResultId(String(existing.id)); clearPending(request.key); setConfirm(false); }
          return;
        }
        if (request.acceptedId !== undefined) { if (mounted.current) setMessage(b.refreshFailed); return; }
      }
      const outcome = await submitEnrollment(employee.id, request);
      if (outcome.kind === "refused") {
        // The server explicitly rejected this transaction; inputs remain editable.
        if (mounted.current) { clearPending(request.key); setConfirm(false); setMessage(b.refused); }
        else { try { removeMatchingJournal(sessionStorage, recoveryKey, request.key); } catch { /* retain journal */ } }
        return;
      }
      if (outcome.kind === "unknown") { if (mounted.current) setMessage(b.uncertain); return; }
      const op = outcome.operation;
      // Keep a known receipt in the recovery journal if the modal closed meanwhile.
      try { markJournalAccepted(sessionStorage, recoveryKey, request, op.id); } catch { /* preserve old journal */ }
      if (!mounted.current) return;
      setAccepted(op); setResultId(String(op.id)); clearPending(request.key); setConfirm(false);
      try { await context.mutate(); } catch { if (mounted.current) setMessage(b.refreshFailed); }
      focusWithin("[data-gate-result]");
    } catch { if (mounted.current) setMessage(b.uncertain); }
    finally { running.current = false; if (mounted.current) setBusy(false); }
  }
  async function backendApply() {
    if (!confirm || blocked || !photo || !checks.every(Boolean) || !targetDevices.length) return;
    if (!reviewedNumber || reviewedNumber !== employeeNumber) { setConfirm(false); setMessage(b.identityChanged); return; }
    if (running.current) return;
    running.current = true; setBusy(true); setMessage("");
    try {
      const asset = await uploadPhoto(employee.id, photo.blob);
      if (!mounted.current) return;
      const request: { key: string; payload: EnrollmentPayload } = { key: crypto.randomUUID(), payload: { expected_employee_no: reviewedNumber, device_ids: targetDevices.map(d => d.id), photo_asset_id: asset.id, reviewed_name: name.trim(), manual_face_reviewed: true as const, action: GateAction.Enroll } };
      sessionStorage.setItem(recoveryKey, JSON.stringify(request));
      setPending(request);
      running.current = false;
      await retryPending(request);
    } catch { setMessage(b.failed); }
    finally { running.current = false; setBusy(false); }
  }
  async function recheck() {
    setBusy(true);
    try {
      const refreshed = await context.mutate();
      if (pending && refreshed) {
        const known = pending.acceptedId !== undefined ? await getOperation(pending.acceptedId) : null;
        const match = findAcceptedOperation(known ? [known] : refreshed.operations, pending);
        if (match) { setAccepted(match); setResultId(String(match.id)); clearPending(pending.key); setConfirm(false); setMessage(""); }
      }
      if (latest && !pending) await getOperation(Number(latest.id));
    } catch { setMessage(b.failed); }
    finally { setBusy(false); }
  }
  async function processBackend(reconnect = false) {
    if (!latest || busy || !canManage) return;
    setBusy(true); setMessage("");
    try { await (reconnect ? reconnectOperation(Number(latest.id)) : processOperation(Number(latest.id))); await context.mutate(); }
    catch { setMessage(b.failed); await context.mutate().catch(() => undefined); }
    finally { setBusy(false); }
  }
  function apply() {
    if (BACKEND_ENABLED) { void backendApply(); return; }
    if (!confirm || blocked || !targetDevices.length || (needsPhoto && (!photo || !checks.every(Boolean)))) return;
    // Deliberate offline fixture on the last target when several devices exist.
    const operation = simulateOperation(action, name.trim(), targetDevices, devices.length > 1 ? devices[devices.length - 1].id : null);
    const targetIds = new Set(operation.targets.map(t => t.deviceId));
    const older = history.map(item => ({ ...item, targets: item.targets.map(t => t.state === GateState.Waiting && targetIds.has(t.deviceId) ? { ...t, state: GateState.Superseded } : t) }));
    saveHistory([operation, ...older].slice(0, 12)); setResultId(operation.id); setConfirm(false); focusWithin("[data-gate-result]");
  }
  function reconnect() {
    if (BACKEND_ENABLED) { void processBackend(true); return; }
    if (!canManage || !latest || !waiting) return;
    focusWithin("[data-gate-result]");
    saveHistory(history.map(item => item.id === latest.id ? { ...item, targets: item.targets.map(t => t.state === GateState.Waiting ? { ...t, state: item.action === GateAction.Revoke ? GateState.Revoked : GateState.Verified } : t) } : item));
  }

  return <Modal open onClose={() => { if (!BACKEND_ENABLED || !running.current) onClose(); }} title={c.title} full>
    <div ref={dialog} role="dialog" aria-modal="true" aria-label={c.title} tabIndex={-1} className={styles.root} data-testid="gate-preview" onKeyDown={event => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled):not([hidden]), [tabindex="0"]'));
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (!first) return;
      if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }}>
      <div className={styles.banner}><span className={styles.previewDot} /><strong>{BACKEND_ENABLED ? b.banner : c.preview}</strong><span>{BACKEND_ENABLED ? b.bannerHelp : c.previewHelp}</span></div>
      <header className={styles.identity}>
        <div className={styles.avatar}>{employee.full_name.split(/\s+/).slice(0, 2).map(n => n[0]).join("")}</div>
        <div className={styles.employee}><span className={styles.eyebrow}>{c.eyebrow}</span><h2>{employee.full_name}</h2><p>{employee.factory_code} <span>·</span> {c.number}: <strong>{employeeNumber || "—"}</strong></p></div>
        <div className={styles.identityBadge}><ShieldCheck size={17} /><span>{c.separate}</span></div>
      </header>
      {!employeeNumber?.trim() && <p className={styles.warning} role="alert">{c.missingNumber}</p>}
      {employee.status === "archived" && <p className={styles.warning}>{BACKEND_ENABLED ? b.archived : c.archived}</p>}
      {!canManage && <p className={styles.warning}>{BACKEND_ENABLED ? b.readonly : c.readonly}</p>}
      {BACKEND_ENABLED && <p className={styles.warning}>{b.pending}</p>}
      {BACKEND_ENABLED && context.data && !context.data.simulator_enabled && <p className={styles.warning}>{b.disabled}</p>}
      <div className={styles.actions} role="group" aria-label={c.action}>
        {Object.values(GateAction).map((value, index) => {
          const Icon = [DoorOpen, ShieldCheck, Camera, ShieldOff][index];
          return <button type="button" key={value} className={`${styles.action} ${action === value ? styles.active : ""} ${value === GateAction.Revoke ? styles.dangerAction : ""}`} aria-pressed={action === value} disabled={BACKEND_ENABLED && value !== GateAction.Enroll} title={BACKEND_ENABLED && value !== GateAction.Enroll ? b.pending : undefined} onClick={() => changeAction(value)}><Icon size={18} /><span>{actionLabel(value)}</span></button>;
        })}
      </div>
      <div className={styles.columns}>
        <section className={styles.content}>
          <div className={styles.sectionTitle}><span>01</span><h3>{needsPhoto ? c.photoTitle : actionLabel(action)}</h3></div>
          {(action === GateAction.Enroll || action === GateAction.Edit) && <label className={styles.field}>{c.name}<input className="input" value={name} maxLength={255} onChange={e => { setName(e.target.value); setConfirm(false); }} disabled={!canManage || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))} /></label>}
          {needsPhoto ? <>
            <div className={styles.photoLayout}>
              <div className={styles.portrait}>
                {camera ? <video ref={video} autoPlay playsInline muted aria-label={c.camera} /> : photo ? <img src={photo.url} alt={c.photoTitle} /> : <div className={styles.portraitPlaceholder}><ImagePlus size={34} strokeWidth={1.2} /><span>{c.noPhoto}</span></div>}
                <span className={styles.faceGuide} aria-hidden="true" />
                <span className={styles.portraitTag}>{photo ? `${photo.width} × ${photo.height}` : c.photoTitle}</span>
              </div>
              <div className={styles.photoTools}><p>{c.photoHelp}</p><input ref={file} hidden type="file" accept="image/jpeg,image/png" onChange={e => { const picked = e.target.files?.[0]; if (picked) void selectPhoto(picked); e.target.value = ""; }} />
                <button type="button" className="btn" data-gate-upload onClick={() => file.current?.click()} disabled={!canManage || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))}><Upload size={16} />{photo ? c.retake : c.upload}</button>
                <button type="button" className="btn" onClick={() => void openCamera()} disabled={!canManage || camera || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))}><Camera size={16} />{c.camera}</button>
                {camera && <><button type="button" className="btn btn-primary" onClick={capture}>{c.capture}</button><button type="button" className="btn" onClick={closeCamera}><X size={15} />{c.stop}</button></>}
                <small>JPG / PNG · ≤ 8 MB<br />{BACKEND_ENABLED ? b.photoMeta : c.photoMeta}</small>
              </div>
            </div>
            <fieldset className={styles.checks}><legend>{c.checks}</legend>{[c.front, c.eyes].map((label, index) => <label key={index}><input type="checkbox" checked={checks[index]} disabled={!photo || !canManage || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))} onChange={e => { setChecks(old => old.map((v, i) => i === index ? e.target.checked : v)); setConfirm(false); }} />{label}</label>)}<p>{BACKEND_ENABLED ? b.quality : c.quality}</p></fieldset>
          </> : <div className={`${styles.explanation} ${action === GateAction.Revoke ? styles.revoke : ""}`}><ShieldCheck size={28} /><p>{action === GateAction.Revoke ? c.revokeHelp : c.detailsHelp}</p><small>{action === GateAction.Revoke ? c.revokePhoto : c.photoOptional}</small></div>}
          <div className={styles.sectionTitle}><span>02</span><h3>{c.devices}</h3></div>
          <div className={styles.deviceHeading}><p>{c.devicesHelp}</p><button type="button" onClick={() => { setSelected(selected.length === devices.length ? [] : devices.map(d => d.id)); setConfirm(false); }} disabled={!devices.length || !canManage || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))}>{selected.length === devices.length && devices.length ? c.none : c.all}</button></div>
          {deviceLoading && <p role="status">{c.loading}</p>}
          {deviceError && <div role="alert" className={styles.warning}>{c.loadError}<button type="button" className="btn" onClick={() => void (BACKEND_ENABLED ? context.mutate() : mutate())}>{c.retry}</button></div>}
          {!deviceLoading && !deviceError && !devices.length && <p className={styles.warning}>{c.empty}</p>}
          <div className={styles.devices}>{devices.map((device, index) => {
            const offline = BACKEND_ENABLED ? device.online !== true : devices.length > 1 && index === devices.length - 1;
            return <label key={device.id} className={`${styles.device} ${selected.includes(device.id) ? styles.deviceSelected : ""}`}><input type="checkbox" checked={selected.includes(device.id)} disabled={!canManage || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))} onChange={e => { setSelected(old => e.target.checked ? [...old, device.id] : old.filter(id => id !== device.id)); setConfirm(false); }} /><div><strong>{device.name}</strong><span>{device.vendor} · {device.device_key}</span><small className={offline ? styles.offline : styles.online}><i />{BACKEND_ENABLED ? (device.online === true ? b.online : device.online === false ? b.offline : b.unknownDevice) : (offline ? c.offline : c.available)}</small></div></label>;
          })}</div>
        </section>
        <aside className={styles.aside}>
          <section className={styles.summary}><span className={styles.eyebrow}>{c.summary}</span><h3>{actionLabel(action)}</h3><p>{c.noAction}</p><dl><div><dt>{c.employee}</dt><dd>{name || employee.full_name}</dd></div><div><dt>{c.number}</dt><dd>{employeeNumber || "—"}</dd></div><div><dt>{c.targets}</dt><dd>{selected.length} / {devices.length}</dd></div>{needsPhoto && <div><dt>{c.photoTitle}</dt><dd>{photo ? c.photoReady : c.noPhoto}</dd></div>}</dl>
            <p className={styles.identityNote}>{c.identity}</p>
            {confirm ? <div className={styles.confirm} tabIndex={-1} data-gate-confirm role="region" aria-label={c.confirmTitle}><strong>{action === GateAction.Revoke ? c.confirmRevoke : c.confirmTitle}</strong><ul>{targetDevices.map(d => <li key={d.id}>{d.name}</li>)}</ul><button type="button" className={`btn ${action === GateAction.Revoke ? styles.revokeButton : "btn-primary"}`} onClick={apply} disabled={blocked || (BACKEND_ENABLED && reviewedNumber !== employeeNumber)}>{action === GateAction.Revoke ? c.revoke : c.apply}<Check size={16} /></button><button type="button" className="btn" onClick={() => setConfirm(false)}>{c.back}</button></div>
              : <button type="button" className="btn btn-primary" onClick={review} disabled={blocked || !devices.length || !name.trim()}>{c.review}<ArrowRight size={16} /></button>}
            {message && <p role="alert" className={styles.error}>{message}</p>}
            {BACKEND_ENABLED && pending && <><button type="button" className="btn" disabled={busy} onClick={() => void recheck()}>{b.recheck}</button><button type="button" className="btn" disabled={busy || pending.acceptedId !== undefined} onClick={() => void retryPending(pending, true)}>{b.retrySubmit}</button></>}
            {BACKEND_ENABLED && busy && <p role="status">{b.uploading}</p>}
          </section>
          {latest && <section className={styles.result} tabIndex={-1} data-gate-result aria-live="polite"><div className={styles.resultHeader}>{waiting || (BACKEND_ENABLED && (!latest.targets.length || !latest.targets.every(t => t.state === GateState.Succeeded))) ? <Clock3 size={19} /> : <CheckCircle2 size={19} />}<h3>{BACKEND_ENABLED ? (latest.targets.length > 0 && latest.targets.every(t => t.state === GateState.Succeeded) ? b.complete : b.pendingResult) : (waiting ? c.partial : c.complete)}</h3></div><p><strong>{actionLabel(latest.action)}</strong> · {BACKEND_ENABLED ? b.resultHelp : c.resultHelp}</p>{latest.targets.map(t => <div key={t.deviceId} className={styles.targetResult}><span>{t.name}</span><strong className={(BACKEND_ENABLED && t.state !== GateState.Succeeded) || t.state === GateState.Waiting ? styles.offline : t.state === GateState.Superseded ? styles.superseded : styles.online}>{t.state === GateState.Waiting || (BACKEND_ENABLED && t.state !== GateState.Succeeded) ? <Clock3 size={13} /> : t.state === GateState.Superseded ? <X size={13} /> : <Check size={13} />}{stateLabel(t.state)}</strong></div>)}{BACKEND_ENABLED && <><button type="button" className="btn" disabled={busy} onClick={() => void recheck()}>{b.recheck}</button>{latest.targets.some(t => [GateState.Queued, GateState.Uncertain, GateState.Processing, GateState.Verifying].includes(t.state)) && <button type="button" className="btn" disabled={busy || !canManage} onClick={() => void processBackend()}>{b.process}</button>}</>}{waiting && <><p>{c.pendingHelp}</p><button type="button" className="btn" onClick={reconnect} disabled={!canManage || (BACKEND_ENABLED && (busy || !!pending || recoveryBlocked))}>{c.retryWaiting}</button></>}</section>}
          <section className={styles.history}><h3>{c.history}</h3>{displayedHistory.length ? displayedHistory.map(item => <button type="button" key={item.id} className={styles.historyItem} aria-pressed={latest?.id === item.id} onClick={() => setResultId(item.id)}><span className={styles.historyDot} /><span><strong>{actionLabel(item.action)}</strong><small>{item.targets.length} {c.selected} · {new Date(item.at).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })}</small>{item.targets.some(t => t.state === GateState.Waiting) && <small className={styles.offline}>{c.waiting}</small>}</span></button>) : <p>{BACKEND_ENABLED ? b.noHistory : c.noHistory}</p>}<small>{BACKEND_ENABLED ? b.stored : c.stored}</small>{storageError && <p role="alert" className={styles.error}>{c.storeError}</p>}</section>
        </aside>
      </div>
      <footer className={styles.footer}><span><ShieldCheck size={16} />{c.coexist}</span><button type="button" className="btn" onClick={onClose} disabled={BACKEND_ENABLED && busy}>{c.close}</button></footer>
    </div>
  </Modal>;
}
