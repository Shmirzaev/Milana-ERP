import { api } from "@/lib/api";
import { ApiError } from "@/lib/errorMessages";
import { GateAction, GateState, type GateOperation } from "./turnstilePreview";

export enum GateMode { Disabled = "disabled", Simulator = "simulator" }
export enum GateBindingState { Pending = "pending", Active = "active", Revoked = "revoked" }
export enum GateErrorCode { DeviceOffline = "device_offline", IdentityConflict = "identity_conflict", PayloadConflict = "payload_conflict", StaleRevision = "stale_revision", LeaseExpired = "lease_expired", SimulatorError = "simulator_error" }

export interface ServerDevice { id: number; name: string; device_key: string; online: boolean }
export interface ServerTarget { id: number; device_id: number; device_name: string; state: GateState; attempts: number; error_code: GateErrorCode | null; baseline_revision?: number | null; baseline_profile_hash?: string | null }
export interface ServerOperation { id: number; employee_id: number; factory_code: string; action: GateAction; mode: GateMode; revision: number; full_name: string; photo_asset_id: number | null; external_person_id: string; created_at: string; targets: ServerTarget[] }
export interface GateContext { employee_id: number; employee_no: string | null; supported_actions: GateAction[]; simulator_enabled: boolean; devices: ServerDevice[]; bindings: { device_id: number; state: GateBindingState; desired_revision: number; edit_baseline?: EditBaseline | null }[]; operations: ServerOperation[] }
export interface EditBaseline { revision: number; profile_hash: string; full_name: string }
export interface EditTarget { device_id: number; expected_revision: number; expected_profile_hash: string }
export interface EditPayload { expected_employee_no: string; reviewed_name: string; action: GateAction.Edit; targets: EditTarget[] }
export interface PhotoPayload { expected_employee_no: string; photo_asset_id: number; manual_face_reviewed: true; action: GateAction.Photo; targets: EditTarget[] }
export type GatePayload = EnrollmentPayload | EditPayload | PhotoPayload;
export interface EnrollmentPayload { expected_employee_no: string; device_ids: number[]; photo_asset_id: number; reviewed_name: string; manual_face_reviewed: true; action: GateAction.Enroll }
const prefix = "/api/turnstile-access";
export const contextUrl = (employeeId: number) => `${prefix}/employees/${employeeId}`;
export const uploadPhoto = (employeeId: number, blob: Blob) => {
  const form = new FormData(); form.append("file", blob, blob.type === "image/png" ? "photo.png" : "photo.jpg");
  return api.postForm<{ id: number }>(`${prefix}/employees/${employeeId}/photos`, form);
};
export const enroll = (employeeId: number, payload: EnrollmentPayload, key: string) => api.postWithHeaders<ServerOperation>(`${prefix}/employees/${employeeId}/enroll`, payload, { "Idempotency-Key": key });
export const getOperation = (id: number) => api.get<ServerOperation>(`${prefix}/operations/${id}`);
export const processOperation = (id: number) => api.post<ServerOperation>(`${prefix}/operations/${id}/simulate`);
export const reconnectOperation = (id: number) => api.post<ServerOperation>(`${prefix}/operations/${id}/simulator-reconnect`);
export function projectOperation(operation: ServerOperation): GateOperation {
  return { id: String(operation.id), action: operation.action, at: operation.created_at, name: operation.full_name,
    targets: operation.targets.map(t => ({ deviceId: t.device_id, name: t.device_name, state: t.state })) };
}

export interface EnrollmentRequest { key: string; payload: GatePayload; acceptedId?: number }
export function validRequest(value: unknown): value is EnrollmentRequest {
  if (!value || typeof value !== "object") return false;
  const r = value as EnrollmentRequest, p = r.payload;
  if (typeof r.key !== "string" || !r.key || !p || typeof p.expected_employee_no !== "string" || !p.expected_employee_no.trim() || p.expected_employee_no.length > 64 || (r.acceptedId !== undefined && (!Number.isInteger(r.acceptedId) || r.acceptedId <= 0))) return false;
  if (p.action === GateAction.Enroll) return typeof p.reviewed_name === "string" && !!p.reviewed_name.trim() && p.reviewed_name.length <= 255 && Array.isArray(p.device_ids) && p.device_ids.length > 0 && p.device_ids.length <= 32 && new Set(p.device_ids).size === p.device_ids.length && p.device_ids.every(x => Number.isInteger(x) && x > 0) && Number.isInteger(p.photo_asset_id) && p.photo_asset_id > 0 && p.manual_face_reviewed === true;
  if (p.action === GateAction.Edit || p.action === GateAction.Photo) return (p.action === GateAction.Edit ? typeof p.reviewed_name === "string" && !!p.reviewed_name.trim() && p.reviewed_name.length <= 255 : Number.isInteger(p.photo_asset_id) && p.photo_asset_id > 0 && p.manual_face_reviewed === true && !("reviewed_name" in p)) && Array.isArray(p.targets) && p.targets.length > 0 && p.targets.length <= 32 && new Set(p.targets.map(t => t?.device_id)).size === p.targets.length && p.targets.every(t => t && Number.isInteger(t.device_id) && t.device_id > 0 && Number.isInteger(t.expected_revision) && t.expected_revision > 0 && typeof t.expected_profile_hash === "string" && /^[0-9a-f]{64}$/.test(t.expected_profile_hash));
  return false;
}
export type SubmissionResult = { kind: "accepted"; operation: ServerOperation } | { kind: "refused"; status: number } | { kind: "unknown" };
const definiteRefusals = new Set([400, 401, 403, 404, 409, 413, 415, 422]);
export async function submitEnrollment(employeeId: number, request: EnrollmentRequest): Promise<SubmissionResult> {
  try {
    let operation: ServerOperation;
    switch (request.payload.action) {
      case GateAction.Enroll: operation = await enroll(employeeId, request.payload, request.key); break;
      case GateAction.Edit: operation = await api.postWithHeaders<ServerOperation>(`${prefix}/employees/${employeeId}/edit`, request.payload, { "Idempotency-Key": request.key }); break;
      case GateAction.Photo: operation = await api.postWithHeaders<ServerOperation>(`${prefix}/employees/${employeeId}/photo`, request.payload, { "Idempotency-Key": request.key }); break;
      default: return { kind: "refused", status: 400 };
    }
    return { kind: "accepted", operation };
  }
  catch (error) {
    if (error instanceof ApiError && definiteRefusals.has(error.status)) return { kind: "refused", status: error.status };
    return { kind: "unknown" };
  }
}
export const lookupRequest = (employeeId: number, request: EnrollmentRequest) => api.getWithHeaders<ServerOperation | null>(prefix + "/employees/" + employeeId + "/requests/" + request.payload.action, { "Idempotency-Key": request.key });

export function findAcceptedOperation(operations: ServerOperation[], request: EnrollmentRequest): ServerOperation | undefined {
  if (request.acceptedId === undefined) return undefined;
  const p = request.payload;
  return operations.find(op => {
    if (op.id !== request.acceptedId || op.external_person_id !== p.expected_employee_no || op.action !== p.action || op.mode !== GateMode.Simulator || new Set(op.targets.map(t => t.device_id)).size !== op.targets.length) return false;
    if (p.action === GateAction.Enroll) return op.full_name === p.reviewed_name && op.photo_asset_id === p.photo_asset_id && op.targets.length === p.device_ids.length && op.targets.every(t => p.device_ids.includes(t.device_id));
    if (p.action !== GateAction.Edit && p.action !== GateAction.Photo) return false;
    if (p.action === GateAction.Edit ? op.full_name !== p.reviewed_name || op.photo_asset_id !== null : op.photo_asset_id !== p.photo_asset_id) return false;
    return op.targets.length === p.targets.length && op.targets.every(t => p.targets.some(ref => ref.device_id === t.device_id && ref.expected_revision === t.baseline_revision && ref.expected_profile_hash === t.baseline_profile_hash));
  });
}

export function removeMatchingJournal(storage: Storage, journalKey: string, requestKey: string): boolean {
  const raw = storage.getItem(journalKey);
  if (!raw) return false;
  const stored: unknown = JSON.parse(raw);
  if (!stored || typeof stored !== "object" || !("key" in stored) || stored.key !== requestKey) return false;
  storage.removeItem(journalKey);
  return true;
}

export function markJournalAccepted(storage: Storage, journalKey: string, request: EnrollmentRequest, acceptedId: number): boolean {
  const raw = storage.getItem(journalKey);
  if (!raw) return false;
  const stored: unknown = JSON.parse(raw);
  if (!stored || typeof stored !== "object" || !("key" in stored) || stored.key !== request.key) return false;
  storage.setItem(journalKey, JSON.stringify({ ...request, acceptedId }));
  return true;
}
