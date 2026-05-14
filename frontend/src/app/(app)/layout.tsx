import Sidebar from "@/components/Sidebar";
import Topbar from "@/components/Topbar";
import AuthGate from "@/components/AuthGate";
import TasksDrawer from "@/components/TasksDrawer";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <div className="flex min-h-screen bg-stone-100">
        <Sidebar />
        <div className="flex-1 flex flex-col">
          <Topbar />
          <main className="flex-1 p-6 lg:p-8">{children}</main>
        </div>
        <TasksDrawer />
      </div>
    </AuthGate>
  );
}
