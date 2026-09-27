import { useMemo } from "react";

export function useCuttingPassportDirectoryKeys(showForm: boolean) {
  return useMemo(() => ({
    operators: showForm ? "/api/cutting-passports/operators" : null,
  }), [showForm]);
}
