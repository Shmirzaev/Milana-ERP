import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import AuthGate from "@/components/AuthGate";
import TasksDrawer from "@/components/TasksDrawer";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="flex min-h-screen min-w-0 flex-col bg-stone-100 lg:flex-row">
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar />
          <main className="min-w-0 flex-1 px-3 pb-24 pt-4 sm:px-4 md:px-5 lg:p-8">{children}</main>
        </div>
        <TasksDrawer />
      </div>
    </AuthGate>
  );
}
