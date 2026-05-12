"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Brain, Database, MessageSquare, Share2, LogOut, GitBranch as GitHubIcon } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useState } from "react";

const NAV_ITEMS = [
  { href: "/repos", label: "Repo Manager", icon: Database },
  { href: "/query", label: "Query", icon: MessageSquare },
  { href: "/graph", label: "Knowledge Graph", icon: Share2 },
];

export default function TopNav() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [signOutOpen, setSignOutOpen] = useState(false);

  const isActive = (href: string): boolean => {
    if (href === "/repos") return pathname === "/repos";
    return pathname === href;
  };

  return (
    <header className="top-nav-wrap">
      <nav className="top-nav glass" aria-label="Primary navigation">
        <Link href="/repos" className="brand" aria-label="Cortex dashboard">
          <span className="app-brand-mark" aria-hidden="true">
            <Brain size={25} strokeWidth={1.55} />
          </span>
          <span>
            <strong>Cortex</strong>
            <small>Code Intelligence</small>
          </span>
        </Link>

        <div className="top-nav-links">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`top-nav-link ${isActive(item.href) ? "active" : ""}`}
              >
                <Icon size={15} /> {item.label}
              </Link>
            );
          })}
        </div>

        <div className="top-nav-user">
          <div className="top-nav-user-meta" title={user?.login || "Anonymous"}>
            {user?.avatar_url ? (
              <img src={user.avatar_url} alt={user.login} className="top-nav-avatar" />
            ) : (
              <GitHubIcon size={16} color="var(--accent)" />
            )}
            <div>
              <strong>{user?.login || "Anonymous"}</strong>
              <small>GitHub</small>
            </div>
          </div>

          <button type="button" className="top-nav-logout" onClick={() => setSignOutOpen(true)}>
            <LogOut size={14} /> Sign out
          </button>
        </div>
      </nav>

      <ConfirmDialog
        open={signOutOpen}
        title="Sign out of Cortex?"
        message="This clears your Cortex session on this browser. GitHub may still remember the GitHub account currently signed in on github.com."
        confirmLabel="Sign out"
        cancelLabel="Cancel"
        onCancel={() => setSignOutOpen(false)}
        onConfirm={() => {
          setSignOutOpen(false);
          void logout();
        }}
      />
    </header>
  );
}
