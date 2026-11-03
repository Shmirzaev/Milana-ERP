"use client";

import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { ArrowRight, Camera, Check, CheckCircle2, Clock3, DoorOpen, ImagePlus, ShieldCheck, ShieldOff, Upload, X } from "lucide-react";
import Modal from "@/components/Modal";
import { fetcher } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { GateAction, GateState, PREVIEW_ENABLED, previewKey, readPreview, simulateOperation, type GateDevice, type GateEmployee, type GateOperation } from "./turnstilePreview";
import { gateCopy } from "./turnstilePreviewCopy";
import styles from "./TurnstileAccessPreview.module.css";

interface Props { employee: GateEmployee; actorId: number; canManage: boolean; onClose: () => void }
interface Photo { url: string; width: number; height: number }

export default function TurnstileAccessPreview(props: Props) {
  // The wrapper prevents even a read request when this development-only preview is disabled.
  return PREVIEW_ENABLED ? <Preview key={`${props.actorId}:${props.employee.factory_code}:${props.employee.id}`} {...props} /> : null;
}

function Preview({ employee, actorId, canManage, onClose }: Props) {
  const { lang } = useT(); const c = gateCopy[lang];
  const { data, error, isLoading, mutate } = useSWR<{ devices: GateDevice[] }>("/api/attendance/overview?page_size=10", fetcher);
  const devices = data?.devices || [];
  const [action, setAction] = useState(GateAction.Enroll);
  const [name, setName] = useState(employee.full_name);
  const [selected, setSelected] = useState<number[]>([]);
  const [photo, setPhoto] = useState<Photo | null>(null);
  const [checks, setChecks] = useState([false, false]);
  const [message, setMessage] = useState(""); const [storageError, setStorageError] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [history, setHistory] = useState<GateOperation[]>([]);
  const [resultId, setResultId] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const video = useRef<HTMLVideoElement>(null); const stream = useRef<MediaStream | null>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const cameraGeneration = useRef(0); const photoGeneration = useRef(0); const mounted = useRef(true);
  const file = useRef<HTMLInputElement>(null); const photoUrl = useRef<string | null>(null);
  const key = previewKey(actorId, employee);
  const needsPhoto = action === GateAction.Enroll || action === GateAction.Photo;
  const latest = history.find(item => item.id === resultId) || history[0];
  const waiting = latest?.targets.some(t => t.state === GateState.Waiting);
  const targetDevices = devices.filter(d => selected.includes(d.id));
  const blocked = !canManage || !employee.employee_no?.trim() || (employee.status === "archived" && action !== GateAction.Revoke);
  const actionLabel = (value: GateAction) => ({ [GateAction.Enroll]: c.enroll, [GateAction.Edit]: c.edit, [GateAction.Photo]: c.photo, [GateAction.Revoke]: c.revoke })[value];
  const stateLabel = (value: GateState) => ({ [GateState.Verified]: c.verified, [GateState.Waiting]: c.waiting, [GateState.Revoked]: c.revoked, [GateState.Superseded]: c.superseded })[value];

  useEffect(() => { setHistory(readPreview(key)); }, [key]);
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
      photoUrl.current = url; setPhoto({ url, width: image.naturalWidth, height: image.naturalHeight }); setChecks([false, false]); setMessage(""); closeCamera();
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
    setMessage(""); setConfirm(true); focusWithin("[data-gate-confirm]");
  }
  function saveHistory(next: GateOperation[]) {
    setHistory(next);
    try { sessionStorage.setItem(key, JSON.stringify(next)); setStorageError(false); } catch { setStorageError(true); }
  }
  function apply() {
    if (!confirm || blocked || !targetDevices.length || (needsPhoto && (!photo || !checks.every(Boolean)))) return;
    // Deliberate offline fixture on the last target when several devices exist.
    const operation = simulateOperation(action, name.trim(), targetDevices, devices.length > 1 ? devices[devices.length - 1].id : null);
    const targetIds = new Set(operation.targets.map(t => t.deviceId));
    const older = history.map(item => ({ ...item, targets: item.targets.map(t => t.state === GateState.Waiting && targetIds.has(t.deviceId) ? { ...t, state: GateState.Superseded } : t) }));
    saveHistory([operation, ...older].slice(0, 12)); setResultId(operation.id); setConfirm(false); focusWithin("[data-gate-result]");
  }
  function reconnect() {
    if (!canManage || !latest || !waiting) return;
    focusWithin("[data-gate-result]");
    saveHistory(history.map(item => item.id === latest.id ? { ...item, targets: item.targets.map(t => t.state === GateState.Waiting ? { ...t, state: item.action === GateAction.Revoke ? GateState.Revoked : GateState.Verified } : t) } : item));
  }

  return <Modal open onClose={onClose} title={c.title} full>
    <div ref={dialog} role="dialog" aria-modal="true" aria-label={c.title} tabIndex={-1} className={styles.root} data-testid="gate-preview" onKeyDown={event => {
      if (event.key !== "Tab") return;
      const focusable = Array.from(event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled):not([hidden]), [tabindex="0"]'));
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (!first) return;
      if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }}>
      <div className={styles.banner}><span className={styles.previewDot} /><strong>{c.preview}</strong><span>{c.previewHelp}</span></div>
      <header className={styles.identity}>
        <div className={styles.avatar}>{employee.full_name.split(/\s+/).slice(0, 2).map(n => n[0]).join("")}</div>
        <div className={styles.employee}><span className={styles.eyebrow}>{c.eyebrow}</span><h2>{employee.full_name}</h2><p>{employee.factory_code} <span>·</span> {c.number}: <strong>{employee.employee_no || "—"}</strong></p></div>
        <div className={styles.identityBadge}><ShieldCheck size={17} /><span>{c.separate}</span></div>
      </header>
      {!employee.employee_no?.trim() && <p className={styles.warning} role="alert">{c.missingNumber}</p>}
      {employee.status === "archived" && <p className={styles.warning}>{c.archived}</p>}
      {!canManage && <p className={styles.warning}>{c.readonly}</p>}
      <div className={styles.actions} role="group" aria-label={c.action}>
        {Object.values(GateAction).map((value, index) => {
          const Icon = [DoorOpen, ShieldCheck, Camera, ShieldOff][index];
          return <button type="button" key={value} className={`${styles.action} ${action === value ? styles.active : ""} ${value === GateAction.Revoke ? styles.dangerAction : ""}`} aria-pressed={action === value} onClick={() => changeAction(value)}><Icon size={18} /><span>{actionLabel(value)}</span></button>;
        })}
      </div>
      <div className={styles.columns}>
        <section className={styles.content}>
          <div className={styles.sectionTitle}><span>01</span><h3>{needsPhoto ? c.photoTitle : actionLabel(action)}</h3></div>
          {(action === GateAction.Enroll || action === GateAction.Edit) && <label className={styles.field}>{c.name}<input className="input" value={name} maxLength={255} onChange={e => { setName(e.target.value); setConfirm(false); }} disabled={!canManage} /></label>}
          {needsPhoto ? <>
            <div className={styles.photoLayout}>
              <div className={styles.portrait}>
                {camera ? <video ref={video} autoPlay playsInline muted aria-label={c.camera} /> : photo ? <img src={photo.url} alt={c.photoTitle} /> : <div className={styles.portraitPlaceholder}><ImagePlus size={34} strokeWidth={1.2} /><span>{c.noPhoto}</span></div>}
                <span className={styles.faceGuide} aria-hidden="true" />
                <span className={styles.portraitTag}>{photo ? `${photo.width} × ${photo.height}` : c.photoTitle}</span>
              </div>
              <div className={styles.photoTools}><p>{c.photoHelp}</p><input ref={file} hidden type="file" accept="image/jpeg,image/png" onChange={e => { const picked = e.target.files?.[0]; if (picked) void selectPhoto(picked); e.target.value = ""; }} />
                <button type="button" className="btn" data-gate-upload onClick={() => file.current?.click()} disabled={!canManage}><Upload size={16} />{photo ? c.retake : c.upload}</button>
                <button type="button" className="btn" onClick={() => void openCamera()} disabled={!canManage || camera}><Camera size={16} />{c.camera}</button>
                {camera && <><button type="button" className="btn btn-primary" onClick={capture}>{c.capture}</button><button type="button" className="btn" onClick={closeCamera}><X size={15} />{c.stop}</button></>}
                <small>JPG / PNG · ≤ 8 MB<br />{c.photoMeta}</small>
              </div>
            </div>
            <fieldset className={styles.checks}><legend>{c.checks}</legend>{[c.front, c.eyes].map((label, index) => <label key={index}><input type="checkbox" checked={checks[index]} disabled={!photo || !canManage} onChange={e => { setChecks(old => old.map((v, i) => i === index ? e.target.checked : v)); setConfirm(false); }} />{label}</label>)}<p>{c.quality}</p></fieldset>
          </> : <div className={`${styles.explanation} ${action === GateAction.Revoke ? styles.revoke : ""}`}><ShieldCheck size={28} /><p>{action === GateAction.Revoke ? c.revokeHelp : c.detailsHelp}</p><small>{action === GateAction.Revoke ? c.revokePhoto : c.photoOptional}</small></div>}
          <div className={styles.sectionTitle}><span>02</span><h3>{c.devices}</h3></div>
          <div className={styles.deviceHeading}><p>{c.devicesHelp}</p><button type="button" onClick={() => { setSelected(selected.length === devices.length ? [] : devices.map(d => d.id)); setConfirm(false); }} disabled={!devices.length || !canManage}>{selected.length === devices.length && devices.length ? c.none : c.all}</button></div>
          {isLoading && <p role="status">{c.loading}</p>}
          {error && <div role="alert" className={styles.warning}>{c.loadError}<button type="button" className="btn" onClick={() => void mutate()}>{c.retry}</button></div>}
          {!isLoading && !error && !devices.length && <p className={styles.warning}>{c.empty}</p>}
          <div className={styles.devices}>{devices.map((device, index) => {
            const offline = devices.length > 1 && index === devices.length - 1;
            return <label key={device.id} className={`${styles.device} ${selected.includes(device.id) ? styles.deviceSelected : ""}`}><input type="checkbox" checked={selected.includes(device.id)} disabled={!canManage} onChange={e => { setSelected(old => e.target.checked ? [...old, device.id] : old.filter(id => id !== device.id)); setConfirm(false); }} /><div><strong>{device.name}</strong><span>{device.vendor} · {device.device_key}</span><small className={offline ? styles.offline : styles.online}><i />{offline ? c.offline : c.available}</small></div></label>;
          })}</div>
        </section>
        <aside className={styles.aside}>
          <section className={styles.summary}><span className={styles.eyebrow}>{c.summary}</span><h3>{actionLabel(action)}</h3><p>{c.noAction}</p><dl><div><dt>{c.employee}</dt><dd>{name || employee.full_name}</dd></div><div><dt>{c.number}</dt><dd>{employee.employee_no || "—"}</dd></div><div><dt>{c.targets}</dt><dd>{selected.length} / {devices.length}</dd></div>{needsPhoto && <div><dt>{c.photoTitle}</dt><dd>{photo ? c.photoReady : c.noPhoto}</dd></div>}</dl>
            <p className={styles.identityNote}>{c.identity}</p>
            {confirm ? <div className={styles.confirm} tabIndex={-1} data-gate-confirm role="region" aria-label={c.confirmTitle}><strong>{action === GateAction.Revoke ? c.confirmRevoke : c.confirmTitle}</strong><ul>{targetDevices.map(d => <li key={d.id}>{d.name}</li>)}</ul><button type="button" className={`btn ${action === GateAction.Revoke ? styles.revokeButton : "btn-primary"}`} onClick={apply} disabled={blocked}>{action === GateAction.Revoke ? c.revoke : c.apply}<Check size={16} /></button><button type="button" className="btn" onClick={() => setConfirm(false)}>{c.back}</button></div>
              : <button type="button" className="btn btn-primary" onClick={review} disabled={blocked || !devices.length || !name.trim()}>{c.review}<ArrowRight size={16} /></button>}
            {message && <p role="alert" className={styles.error}>{message}</p>}
          </section>
          {latest && <section className={styles.result} tabIndex={-1} data-gate-result aria-live="polite"><div className={styles.resultHeader}>{waiting ? <Clock3 size={19} /> : <CheckCircle2 size={19} />}<h3>{waiting ? c.partial : c.complete}</h3></div><p><strong>{actionLabel(latest.action)}</strong> · {c.resultHelp}</p>{latest.targets.map(t => <div key={t.deviceId} className={styles.targetResult}><span>{t.name}</span><strong className={t.state === GateState.Waiting ? styles.offline : t.state === GateState.Superseded ? styles.superseded : styles.online}>{t.state === GateState.Waiting ? <Clock3 size={13} /> : t.state === GateState.Superseded ? <X size={13} /> : <Check size={13} />}{stateLabel(t.state)}</strong></div>)}{waiting && <><p>{c.pendingHelp}</p><button type="button" className="btn" onClick={reconnect} disabled={!canManage}>{c.retryWaiting}</button></>}</section>}
          <section className={styles.history}><h3>{c.history}</h3>{history.length ? history.map(item => <button type="button" key={item.id} className={styles.historyItem} aria-pressed={latest?.id === item.id} onClick={() => setResultId(item.id)}><span className={styles.historyDot} /><span><strong>{actionLabel(item.action)}</strong><small>{item.targets.length} {c.selected} · {new Date(item.at).toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" })}</small>{item.targets.some(t => t.state === GateState.Waiting) && <small className={styles.offline}>{c.waiting}</small>}</span></button>) : <p>{c.noHistory}</p>}<small>{c.stored}</small>{storageError && <p role="alert" className={styles.error}>{c.storeError}</p>}</section>
        </aside>
      </div>
      <footer className={styles.footer}><span><ShieldCheck size={16} />{c.coexist}</span><button type="button" className="btn" onClick={onClose}>{c.close}</button></footer>
    </div>
  </Modal>;
}
