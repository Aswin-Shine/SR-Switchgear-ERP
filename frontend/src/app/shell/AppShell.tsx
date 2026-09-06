import { SessionProvider } from "@/auth/SessionProvider";
import { ToastProvider } from "@/components/Toast";
import { Outlet } from "react-router";
import { ErrorBoundary } from "./ErrorBoundary";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppShell() {
  return (
    <ToastProvider>
      <SessionProvider>
        <div className="app">
          <a className="skip-link" href="#main">
            Skip to content
          </a>
          <Sidebar />
          <TopBar />
          <main className="main" id="main" tabIndex={-1}>
            <ErrorBoundary>
              <Outlet />
            </ErrorBoundary>
          </main>
        </div>
      </SessionProvider>
    </ToastProvider>
  );
}
