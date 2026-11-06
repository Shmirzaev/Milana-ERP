import AppShell from "@/components/AppShell";
import AuthGate from "@/components/AuthGate";
import { Suspense } from "react";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={<div className="p-6" aria-busy="true" />}>
    <AuthGate>
      <AppShell>{children}</AppShell>
    </AuthGate>
    </Suspense>
  );
}
