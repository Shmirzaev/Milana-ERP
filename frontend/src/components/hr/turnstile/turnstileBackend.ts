import { api } from "@/lib/api";
import { ApiError } from "@/lib/errorMessages";
import { GateAction, GateState, type GateOperation } from "./turnstilePreview";

export enum GateMode { Disabled = "disabled", Simulator = "simulator" }
export enum GateBindingState { Pending = "pending", Active = "active", Revoked = "revoked" }
export enum GateErrorCode { DeviceOffline = "device_offline", IdentityConflict = "identity_conflict", PayloadConflict = "payload_conflict", StaleRevision = "stale_revision", LeaseExpired = "lease_expired", SimulatorError = "simulator_error" }

export interface ServerDevice { id: number; name: string; device_key: string; online: boolean }
export interface ServerTarget { id: number; device_id: number; device_name: string; state: GateState; attempts: number; error_code: GateErrorCode | null }
export interface ServerOperation { id: number; employee_id: number; factory_code: string; action: GateAction; mode: GateMode; revision: number; full_name: string; photo_asset_id: number; external_person_id: string; created_at: string; targets: ServerTarget[] }
export interface GateContext { employee_id: number; employee_no: string | null; supported_actions: GateAction[]; simulator_enabled: boolean; devices: ServerDevice[]; bindings: { device_id: number; state: GateBindingState; desired_revision: number }[]; operations: ServerOperation[] }
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

export interface EnrollmentRequest { key: string; payload: EnrollmentPayload; acceptedId?: number }
export type SubmissionResult = { kind: "accepted"; operation: ServerOperation } | { kind: "refused"; status: number } | { kind: "unknown" };
const definiteRefusals = new Set([400, 401, 403, 404, 409, 413, 415, 422]);
export async function submitEnrollment(employeeId: number, request: EnrollmentRequest): Promise<SubmissionResult> {
  try { return { kind: "accepted", operation: await enroll(employeeId, request.payload, request.key) }; }
  catch (error) {
    if (error instanceof ApiError && definiteRefusals.has(error.status)) return { kind: "refused", status: error.status };
    return { kind: "unknown" };
  }
}
export function findAcceptedOperation(operations: ServerOperation[], request: EnrollmentRequest): ServerOperation | undefined {
  return operations.find(op => op.external_person_id === request.payload.expected_employee_no && op.action === GateAction.Enroll && op.mode === GateMode.Simulator && (request.acceptedId === undefined || op.id === request.acceptedId) && op.photo_asset_id === request.payload.photo_asset_id && op.full_name === request.payload.reviewed_name && op.targets.length === request.payload.device_ids.length && op.targets.every(t => request.payload.device_ids.includes(t.device_id)));
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
