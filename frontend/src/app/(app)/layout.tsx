import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import AuthGate from "@/components/AuthGate";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="flex min-h-screen w-full min-w-0 max-w-full flex-col bg-stone-100 min-[1440px]:flex-row">
        <Sidebar />
        <div className="flex w-full min-w-0 max-w-full flex-1 flex-col">
          <Topbar />
          <main className="min-w-0 max-w-full flex-1 px-3 pb-[calc(1.5rem+env(safe-area-inset-bottom))] pt-4 sm:px-4 md:px-5 lg:px-6 lg:pt-6 min-[1440px]:px-8 min-[1440px]:pb-[calc(2rem+env(safe-area-inset-bottom))] min-[1440px]:pt-8">{children}</main>
        </div>
      </div>
    </AuthGate>
  );
}
