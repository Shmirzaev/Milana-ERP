import { api } from "@/lib/api";
import { GateBindingState } from "./turnstileBackend";
export const LIVE_ENABLED = process.env.NEXT_PUBLIC_TURNSTILE_LIVE === "1";
export const livePrefix = "/api/turnstile-live";
export enum LiveAction { Observe = "observe", Enroll = "enroll", Edit = "edit", Photo = "photo", Revoke = "revoke", Restore = "restore", Delete = "delete" }
export enum LiveState { Queued = "queued", Processing = "processing", Dispatching = "dispatching", Succeeded = "succeeded", Conflict = "conflict", Failed = "failed", Uncertain = "uncertain" }
export enum PhysicalUserType { Normal = "normal", Visitor = "visitor", Blocked = "blackList" }
export enum DoubleLockCapability { Unknown = "unknown", Advertised = "advertised", NotAdvertised = "not_advertised" }
export interface PhysicalSnapshot {
  external_person_id: string; present: boolean; full_name: string | null; user_type: PhysicalUserType | null;
  policy: { validity: { enabled: boolean; begin: string; end: string }; right_plans: { door_no: number; plan_template_no: string }[] } | null;
  photo_sha256: string | null; face_count: number; card_count: number; fingerprint_count: number; other_fields_hash: string | null;
  local_ui_right: boolean | null; double_lock_right: boolean | null;
  security_capabilities?: { user_info_sha256: string; double_lock: DoubleLockCapability } | null;
}
export interface LiveJob { id: number; employee_id: number; device_id: number; action: LiveAction; state: LiveState; created_at: string; observation: PhysicalSnapshot | null; profile_hash: string | null }
export interface LiveContext {
  enabled: boolean; employee_no: string | null;
  devices: { id: number; name: string; writes_enabled: boolean; identity_allowed: boolean }[];
  profiles: { device_id: number; state: GateBindingState; profile_hash: string | null; snapshot: PhysicalSnapshot | null; observed_at: string | null }[];
  jobs: LiveJob[];
}
export interface LivePayload {
  expected_employee_no: string; action: LiveAction; device_id: number; expected_profile_hash?: string;
  reviewed_name?: string; photo_asset_id?: number; manual_face_reviewed?: boolean; delete_credentials_confirmed?: boolean;
}
export interface PendingLiveRequest { key: string; payload: LivePayload }
export function validLiveRequest(value: unknown): value is PendingLiveRequest {
  if (!value || typeof value !== "object") return false;
  const r = value as PendingLiveRequest, p = r.payload;
  return typeof r.key === "string" && r.key.length > 0 && r.key.length <= 128 && !!p && Object.values(LiveAction).includes(p.action)
    && typeof p.expected_employee_no === "string" && !!p.expected_employee_no.trim() && p.expected_employee_no.length <= 64
    && Number.isInteger(p.device_id) && p.device_id > 0;
}
export const submitLive = (employeeId: number, request: PendingLiveRequest) => api.postWithHeaders<LiveJob>(`${livePrefix}/employees/${employeeId}/jobs`, request.payload, { "Idempotency-Key": request.key });
export const lookupLive = (employeeId: number, key: string) => api.getWithHeaders<LiveJob | null>(`${livePrefix}/employees/${employeeId}/request`, { "Idempotency-Key": key });
