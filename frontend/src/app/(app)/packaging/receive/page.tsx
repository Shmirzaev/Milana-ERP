"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";

/** Preserve old bookmarks while removing the manual Sewing acceptance step. */
export default function PackagingReceivePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const department = searchParams.get("packaging_department");
  useEffect(() => {
    router.replace(`/packaging/queue${department ? `?packaging_department=${encodeURIComponent(department)}` : ""}`);
  }, [department, router]);
  return null;
}
