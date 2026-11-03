// UI rehearsal only. Device outcomes here are never enrollment evidence.
export enum GateAction { Enroll = "enroll", Edit = "edit", Photo = "photo", Revoke = "revoke" }
export enum GateState { Verified = "verified", Waiting = "waiting", Revoked = "revoked", Superseded = "superseded" }
export interface GateEmployee { id: number; factory_code: string; employee_no: string | null; full_name: string; status: string }
export interface GateDevice { id: number; name: string; device_key: string; vendor: string; last_seen_at: string | null }
export interface GateTarget { deviceId: number; name: string; state: GateState }
export interface GateOperation { id: string; action: GateAction; at: string; name: string; targets: GateTarget[] }

export const PREVIEW_ENABLED = process.env.NEXT_PUBLIC_TURNSTILE_UI_PREVIEW === "1";
export const previewKey = (actor: number, employee: GateEmployee) => `turnstile-preview:v1:${actor}:${employee.factory_code}:${employee.id}`;

export function readPreview(key: string): GateOperation[] {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(key) || "[]");
    if (!Array.isArray(raw)) return [];
    return raw.filter((item): item is GateOperation => {
      if (!item || typeof item !== "object") return false;
      const r = item as Partial<GateOperation>;
      return typeof r.id === "string" && typeof r.name === "string" && typeof r.at === "string"
        && Number.isFinite(Date.parse(r.at)) && Object.values(GateAction).includes(r.action as GateAction)
        && Array.isArray(r.targets) && r.targets.every(t => typeof t?.deviceId === "number"
          && typeof t.name === "string" && Object.values(GateState).includes(t.state));
    }).slice(0, 12);
  } catch { return []; }
}

export function simulateOperation(action: GateAction, name: string, devices: GateDevice[], waitingId: number | null): GateOperation {
  return { id: crypto.randomUUID(), action, name, at: new Date().toISOString(), targets: devices.map(device => ({
    deviceId: device.id, name: device.name,
    state: device.id === waitingId ? GateState.Waiting : action === GateAction.Revoke ? GateState.Revoked : GateState.Verified,
  })) };
}
