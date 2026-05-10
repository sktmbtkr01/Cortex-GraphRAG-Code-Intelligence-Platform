"use client";

import { usePathname } from "next/navigation";
import { useAuth } from "@/context/AuthContext";
import TopNav from "@/components/TopNav";
import GlobalBrainBar from "@/components/GlobalBrainBar";
import NeuralLoader from "@/components/NeuralLoader";
import { NeuralNoise } from "@/components/ui/neural-noise";

// Pages that don't require authentication
const PUBLIC_PAGES = ["/", "/login", "/auth/callback"];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isAuthenticated, isLoading } = useAuth();
  const showGlobalBrain = pathname !== "/repos" && pathname !== "/query";

  // Public pages (login, callback) render without the sidebar shell
  if (PUBLIC_PAGES.includes(pathname)) {
    return <>{children}</>;
  }

  // Show loading state while checking auth
  if (isLoading) {
    return <NeuralLoader status="Warming up Cortex" detail="Mapping your repository brain" />;
  }

  // Redirect to login if not authenticated
  if (!isAuthenticated) {
    // Use a client-side redirect
    if (typeof window !== "undefined") {
      window.location.href = "/";
    }
    return null;
  }

  // Authenticated: render full app shell with top navigation
  return (
    <div className="app-shell-top">
      <NeuralNoise color={[0.28, 0.86, 0.36]} opacity={0.24} speed={0.00075} />
      <TopNav />
      {showGlobalBrain && <GlobalBrainBar />}
      <main className="content top-shell-content">{children}</main>
    </div>
  );
}
