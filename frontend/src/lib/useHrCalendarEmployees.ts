"use client";

import useSWR from "swr";
import { fetcher } from "@/lib/api";

export type HrCalendarEmployee = { id: number; full_name: string };

/** Employee choices are only needed while the create-event modal is open. */
export function useHrCalendarEmployees(open: boolean) {
  return useSWR<HrCalendarEmployee[]>(open ? "/api/employees" : null, fetcher);
}
