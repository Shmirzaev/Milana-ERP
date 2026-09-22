import { useMemo } from "react";

export function useCuttingPassportDirectoryKeys(showForm: boolean) {
  return useMemo(() => ({
    productionOrders: showForm ? "/api/production-orders?page_size=500" : null,
    operators: showForm ? "/api/cutting-passports/operators" : null,
  }), [showForm]);
}
