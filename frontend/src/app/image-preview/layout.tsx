import { Suspense } from "react";
import AuthGate from "@/components/AuthGate";

export default function ImagePreviewLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="p-6" aria-busy="true" />}>
      <AuthGate>{children}</AuthGate>
    </Suspense>
  );
}
