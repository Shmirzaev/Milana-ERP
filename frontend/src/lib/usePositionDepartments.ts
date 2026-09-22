import useSWR from "swr";
import { fetcher } from "@/lib/api";

export type PositionDepartment = { id: number; name: string };

export function positionDepartmentsKey(editing: unknown) {
  return editing === null ? null : "/api/departments";
}

export function usePositionDepartments(editing: unknown) {
  return useSWR<PositionDepartment[]>(positionDepartmentsKey(editing), fetcher);
}
