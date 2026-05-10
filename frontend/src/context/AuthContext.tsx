"use client";

import React, { createContext, useContext, useState, useEffect, useCallback } from "react";

interface User {
  user_id: string;
  login: string;
  provider: "github";
  avatar_url?: string | null;
}

interface AuthState {
  user: User | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  loginWithGitHub: () => void;
  logout: () => Promise<void>;
  authHeaders: () => HeadersInit;
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
  });

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/auth/me`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          setState({
            user: {
              user_id: data.user_id,
              login: data.login,
              provider: data.provider,
              avatar_url: data.avatar_url,
            },
            isLoading: false,
            isAuthenticated: true,
          });
          return;
        }
      } catch {
        // Treat network/auth failures as unauthenticated.
      }
      setState({ user: null, isLoading: false, isAuthenticated: false });
    })();
  }, []);

  const loginWithGitHub = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/github/login`);
      const data = await res.json();
      if (data.url) {
        window.location.href = data.url;
      } else {
        console.error("GitHub OAuth not configured:", data.error);
        alert("GitHub OAuth is not configured on the server.");
      }
    } catch (e) {
      console.error("Failed to get GitHub login URL", e);
    }
  }, []);

  const handleGitHubCallback = useCallback(async (code: string) => {
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/github/callback`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
      if (!res.ok) return false;
      const data = await res.json();

      setState({
        user: {
          user_id: data.user.user_id,
          login: data.user.login,
          provider: "github",
          avatar_url: data.user.avatar_url,
        },
        isLoading: false,
        isAuthenticated: true,
      });
      return true;
    } catch (e) {
      console.error("GitHub callback failed", e);
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch {
      // Still clear local state.
    }
    setState({ user: null, isLoading: false, isAuthenticated: false });
    if (typeof window !== "undefined") {
      window.location.href = "/";
    }
  }, []);

  const authHeaders = useCallback((): HeadersInit => {
    return { "Content-Type": "application/json" };
  }, []);

  const apiFetch = useCallback((path: string, init?: RequestInit): Promise<Response> => {
    const url = path.startsWith("http") ? path : `${API_URL}${path}`;
    return fetch(url, { ...init, credentials: "include" });
  }, []);

  const value: AuthContextValue = {
    ...state,
    loginWithGitHub,
    logout,
    authHeaders,
    apiFetch,
  };

  (globalThis as any).__cortex_handle_github_callback = handleGitHubCallback;

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider");
  return ctx;
}
