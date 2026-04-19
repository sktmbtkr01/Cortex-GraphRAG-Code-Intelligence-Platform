"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface User {
  user_id: string;
  login: string;
  provider: "github" | "guest";
  avatar_url?: string | null;
}

interface AuthState {
  user: User | null;
  accessToken: string | null;
  githubToken: string | null; // Ephemeral — in-memory only, NEVER localStorage
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  loginWithGitHub: () => void;
  loginAsGuest: (name?: string) => Promise<void>;
  logout: () => void;
  authHeaders: () => HeadersInit;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    accessToken: null,
    githubToken: null,
    isLoading: true,
    isAuthenticated: false,
  });

  // Restore session from localStorage (JWT only, never the GitHub token)
  useEffect(() => {
    const stored = localStorage.getItem("cortex_auth");
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        setState({
          user: parsed.user,
          accessToken: parsed.accessToken,
          githubToken: null, // Ephemeral — gone on refresh
          isLoading: false,
          isAuthenticated: true,
        });
      } catch {
        localStorage.removeItem("cortex_auth");
        setState((s) => ({ ...s, isLoading: false }));
      }
    } else {
      setState((s) => ({ ...s, isLoading: false }));
    }
  }, []);

  // Persist JWT + user (but NOT githubToken)
  const persistSession = (user: User, accessToken: string) => {
    localStorage.setItem("cortex_auth", JSON.stringify({ user, accessToken }));
  };

  // GitHub OAuth — redirect to GitHub
  const loginWithGitHub = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/github/login`);
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        console.error("GitHub OAuth not configured:", data.error);
        alert("GitHub OAuth is not configured on the server. Use Guest mode instead.");
      }
    } catch (e) {
      console.error("Failed to get GitHub login URL", e);
    }
  }, []);

  // Guest login — no GitHub needed
  const loginAsGuest = useCallback(async (name?: string) => {
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/guest`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: name || "Guest" }),
      });
      const data = await res.json();

      const user: User = {
        user_id: data.user.user_id,
        login: data.user.login,
        provider: "guest",
        avatar_url: null,
      };

      persistSession(user, data.access_token);
      setState({
        user,
        accessToken: data.access_token,
        githubToken: null,
        isLoading: false,
        isAuthenticated: true,
      });
    } catch (e) {
      console.error("Guest login failed", e);
    }
  }, []);

  // Handle GitHub OAuth callback (called from /auth/callback page)
  const handleGitHubCallback = useCallback(async (code: string) => {
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/github/callback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      const data = await res.json();

      const user: User = {
        user_id: data.user.user_id,
        login: data.user.login,
        provider: "github",
        avatar_url: data.user.avatar_url,
      };

      persistSession(user, data.access_token);
      setState({
        user,
        accessToken: data.access_token,
        githubToken: data.github_token, // Ephemeral — lives only in memory
        isLoading: false,
        isAuthenticated: true,
      });

      return true;
    } catch (e) {
      console.error("GitHub callback failed", e);
      return false;
    }
  }, []);

  // Logout
  const logout = useCallback(() => {
    localStorage.removeItem("cortex_auth");
    setState({
      user: null,
      accessToken: null,
      githubToken: null,
      isLoading: false,
      isAuthenticated: false,
    });
  }, []);

  // Auth headers for API calls
  const authHeaders = useCallback((): HeadersInit => {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (state.accessToken) {
      headers["Authorization"] = `Bearer ${state.accessToken}`;
    }
    // Pass ephemeral GitHub token for privileged API calls
    if (state.githubToken) {
      headers["X-GitHub-Token"] = state.githubToken;
    }
    return headers;
  }, [state.accessToken, state.githubToken]);

  const value: AuthContextValue = {
    ...state,
    loginWithGitHub,
    loginAsGuest,
    logout,
    authHeaders,
  };

  // Expose handleGitHubCallback via a global for the callback page
  (globalThis as any).__cortex_handle_github_callback = handleGitHubCallback;

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
