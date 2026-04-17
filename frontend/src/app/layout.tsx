import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Cortex",
  description: "GitHub codebase intelligence platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="app-shell">
          <aside className="sidebar" aria-label="Primary navigation">
            <Link href="/" className="brand" aria-label="Cortex home">
              <span className="brand-mark">Cx</span>
              <span>
                <strong>Cortex</strong>
                <small>Code Intelligence</small>
              </span>
            </Link>
            <nav className="nav-links">
              <Link href="/">Chat</Link>
              <Link href="/repos">Repos</Link>
              <Link href="/graph">Graph</Link>
            </nav>
            <div className="sidebar-status">
              <span>Phase 0</span>
              <strong>Scaffold</strong>
            </div>
          </aside>
          <main className="content">{children}</main>
        </div>
      </body>
    </html>
  );
}
