"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, GitBranch as GitHubIcon, Shield, Zap } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

export default function LoginPage() {
  const { loginWithGitHub, isAuthenticated } = useAuth();
  const router = useRouter();

  React.useEffect(() => {
    if (isAuthenticated) router.push("/repos");
  }, [isAuthenticated, router]);

  return (
    <section style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 520 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 32 }}>
          <span className="brand-mark" style={{ width: 56, height: 56, fontSize: 22, display: "grid", placeItems: "center", border: "1px solid var(--accent)", color: "var(--accent-strong)", fontWeight: 600 }}>Cx</span>
          <h1 style={{ fontSize: "2.4rem", marginTop: 12 }}>Cortex</h1>
          <p style={{ color: "var(--muted)", marginTop: 4 }}>GitHub Codebase Intelligence</p>
        </div>

        <div className="login-card login-card-primary">
          <div className="login-card-icon">
            <GitHubIcon size={28} />
          </div>
          <h2>Sign in with GitHub</h2>
          <p style={{ fontSize: "0.85rem", color: "var(--muted)", lineHeight: 1.5, marginBottom: 16 }}>
            Connect GitHub to index your repositories, choose branches, query code, inspect graph context, and run repo health checks.
          </p>
          <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: "0.85rem", marginBottom: 24 }}>
            <li style={{ display: "flex", alignItems: "center", gap: 8 }}><Shield size={14} /> Private repo access</li>
            <li style={{ display: "flex", alignItems: "center", gap: 8 }}><Zap size={14} /> Full code intelligence</li>
          </ul>
          <button className="login-btn login-btn-github" onClick={loginWithGitHub}>
            <GitHubIcon size={18} /> Continue with GitHub <ArrowRight size={16} />
          </button>
        </div>

        <p style={{ textAlign: "center", color: "var(--muted)", fontSize: 13, marginTop: 32 }}>
          Your GitHub access token is used in-memory only and never stored persistently.
        </p>
      </div>
    </section>
  );
}
