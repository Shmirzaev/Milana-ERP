export function employeeNumberPayload(current: string | null | undefined, value: string) {
  const next = value.trim() || null;
  return current === undefined || next !== current ? { employee_no: next } : {};
}
