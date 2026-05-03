"use client";

import React, { useState } from "react";
import { useAuth } from "@/context/AuthContext";
import { useRouter } from "next/navigation";
import { GitBranch as GitHubIcon, User, ArrowRight, Shield, Zap } from "lucide-react";

export default function LoginPage() {
  const { loginWithGitHub, loginAsGuest, isAuthenticated } = useAuth();
  const [guestName, setGuestName] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  // Redirect if already authenticated
  React.useEffect(() => {
    if (isAuthenticated) router.push("/repos");
  }, [isAuthenticated, router]);

  const handleGuest = async () => {
    setLoading(true);
    await loginAsGuest(guestName || "Guest");
    setLoading(false);
    router.push("/repos");
  };

  return (
    <section style={{ display: "flex", alignItems: "center", justifyContent: "center", minHeight: "100vh", padding: 24 }}>
      <div style={{ width: "100%", maxWidth: 720 }}>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 32 }}>
          <span className="brand-mark" style={{ width: 56, height: 56, fontSize: 22, display: "grid", placeItems: "center", border: "1px solid var(--accent)", color: "var(--accent-strong)", fontWeight: 600 }}>Cx</span>
          <h1 style={{ fontSize: "2.4rem", marginTop: 12 }}>Cortex</h1>
          <p style={{ color: "var(--muted)", marginTop: 4 }}>GitHub Codebase Intelligence</p>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 18 }}>
          {/* GitHub OAuth */}
          <div className="login-card login-card-primary">
            <div className="login-card-icon">
              <GitHubIcon size={28} />
            </div>
            <h2>Sign in with GitHub</h2>
            <p style={{ fontSize: "0.85rem", color: "var(--muted)", lineHeight: 1.5, marginBottom: 16 }}>Access your public and private repositories. Your code is never stored on disk.</p>
            <ul style={{ listStyle: "none", display: "flex", flexDirection: "column", gap: 8, fontSize: "0.85rem", marginBottom: 24 }}>
              <li style={{ display: "flex", alignItems: "center", gap: 8 }}><Shield size={14} /> Private repo access</li>
              <li style={{ display: "flex", alignItems: "center", gap: 8 }}><Zap size={14} /> Full code intelligence</li>
            </ul>
            <button className="login-btn login-btn-github" onClick={loginWithGitHub}>
              <GitHubIcon size={18} /> Continue with GitHub <ArrowRight size={16} />
            </button>
          </div>

          {/* Guest Mode */}
          <div className="login-card">
            <div className="login-card-icon" style={{ background: "var(--panel-strong)" }}>
              <User size={28} />
            </div>
            <h2>Explore as Guest</h2>
            <p style={{ fontSize: "0.85rem", color: "var(--muted)", lineHeight: 1.5, marginBottom: 16 }}>Search the global public index of open-source repositories without authentication.</p>
            <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
              <input
                value={guestName}
                onChange={(e) => setGuestName(e.target.value)}
                placeholder="Your name (optional)"
                style={{ flex: 1, padding: "0 14px", border: "1px solid var(--line)", background: "#12150f", color: "var(--foreground)" }}
              />
              <button
                className="login-btn"
                onClick={handleGuest}
                disabled={loading}
              >
                {loading ? "..." : "Enter"} <ArrowRight size={16} />
              </button>
            </div>
          </div>
        </div>

        <p style={{ textAlign: "center", color: "var(--muted)", fontSize: 13, marginTop: 32 }}>
          Your GitHub access token is used in-memory only and never stored persistently.
        </p>
      </div>
    </section>
  );
}
