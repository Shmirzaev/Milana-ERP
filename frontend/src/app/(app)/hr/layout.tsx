import { HrWorkspaceNav } from "@/components/hr/HrUi";

export default function HrWorkspaceLayout({ children }: { children: React.ReactNode }) {
  return (
    <div>
      <HrWorkspaceNav />
      {children}
    </div>
  );
}
