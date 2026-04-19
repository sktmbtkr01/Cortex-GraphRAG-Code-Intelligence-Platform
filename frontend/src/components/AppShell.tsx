"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import Sidebar from "@/components/Sidebar";

// Pages that don't require authentication
const PUBLIC_PAGES = ["/login", "/auth/callback"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useAuth();

  // Public pages (login, callback) render without the sidebar shell
  if (PUBLIC_PAGES.includes(pathname)) {
    return <>{children}</>;
  }

  // Show loading state while checking auth
  if (isLoading) {
    return (
      <div className="login-page">
        <div style={{ textAlign: "center" }}>
          <span className="brand-mark" style={{ width: 56, height: 56, fontSize: 22, margin: "0 auto" }}>Cx</span>
          <p style={{ marginTop: 16, color: "var(--muted)" }}>Loading...</p>
        </div>
      </div>
    );
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    // Use a client-side redirect
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    return null;
  }

  // Authenticated: render full app shell with sidebar
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="content">{children}</main>
    </div>
  );
}
