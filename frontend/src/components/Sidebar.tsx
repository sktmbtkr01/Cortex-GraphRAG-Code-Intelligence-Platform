"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { MessageSquare, Database, Share2, LogOut, GitBranch as GitHubIcon } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import ConfirmDialog from "@/components/ConfirmDialog";
import { useState } from "react";

export default function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [signOutOpen, setSignOutOpen] = useState(false);

  return (
    <aside className="sidebar" aria-label="Primary navigation">
      <Link href="/" className="brand" aria-label="Cortex home">
        <span className="brand-mark">Cx</span>
        <span>
          <strong>Cortex</strong>
          <small>Code Intelligence</small>
        </span>
      </Link>
      <nav className="nav-links">
        <Link 
          href="/" 
          style={{ 
            display: "flex", gap: "8px", alignItems: "center",
            borderColor: pathname === "/" ? "var(--line)" : "transparent",
            background: pathname === "/" ? "var(--panel)" : "transparent"
          }}
        >
          <MessageSquare size={16} /> Intel
        </Link>
        <Link 
          href="/repos" 
          style={{ 
            display: "flex", gap: "8px", alignItems: "center",
            borderColor: pathname === "/repos" ? "var(--line)" : "transparent",
            background: pathname === "/repos" ? "var(--panel)" : "transparent"
          }}
        >
          <Database size={16} /> The Dock
        </Link>
        <Link 
          href="/graph" 
          style={{ 
            display: "flex", gap: "8px", alignItems: "center",
            borderColor: pathname === "/graph" ? "var(--line)" : "transparent",
            background: pathname === "/graph" ? "var(--panel)" : "transparent"
          }}
        >
          <Share2 size={16} /> Graph 3D
        </Link>
      </nav>

      {/* User Profile & Logout */}
      <div className="sidebar-user">
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          {user?.avatar_url ? (
            <img
              src={user.avatar_url}
              alt={user.login}
              style={{ width: 32, height: 32, borderRadius: "50%", border: "1px solid var(--line)" }}
            />
          ) : (
            <GitHubIcon size={20} color="var(--accent)" />
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <strong style={{ display: "block", fontSize: 13, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {user?.login || "Anonymous"}
            </strong>
            <small style={{ color: "var(--muted)", fontSize: 11 }}>
              GitHub
            </small>
          </div>
        </div>
        <button
          onClick={() => setSignOutOpen(true)}
          title="Sign out"
          style={{
            background: "transparent",
            border: "1px solid var(--line)",
            color: "var(--muted)",
            padding: "6px 10px",
            marginTop: 10,
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 6,
            fontSize: 12,
          }}
        >
          <LogOut size={14} /> Sign out
        </button>
      </div>
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
    </aside>
  );
}
