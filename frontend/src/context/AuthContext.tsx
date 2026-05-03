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
  isLoading: boolean;
  isAuthenticated: boolean;
}

interface AuthContextValue extends AuthState {
  loginWithGitHub: () => void;
  loginAsGuest: (name?: string) => Promise<void>;
  logout: () => Promise<void>;
  authHeaders: () => HeadersInit;
  apiFetch: (path: string, init?: RequestInit) => Promise<Response>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/**
 * Cookie-based auth. The JWT lives ONLY in an HttpOnly cookie set by the
 * backend. The browser never sees a token string. The GitHub access token
 * lives server-side in a session store keyed by user_id and is looked up
 * per-request — the frontend no longer ships it in any header.
 *
 * All requests that need the session cookie MUST set credentials: "include".
 * Use `apiFetch()` or remember to pass it manually.
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    isLoading: true,
    isAuthenticated: false,
  });

  // On mount, ask the backend "who am I?" using the cookie.
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
      } catch (e) {
        // network failure — treat as unauthenticated
      }
      setState({ user: null, isLoading: false, isAuthenticated: false });
    })();
  }, []);

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

  // Guest login — cookie gets set by the server on success
  const loginAsGuest = useCallback(async (name?: string) => {
    try {
      const res = await fetch(`${API_URL}/api/v1/auth/guest`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ display_name: name || "Guest" }),
      });
      if (!res.ok) throw new Error("Guest login failed");
      const data = await res.json();

      setState({
        user: {
          user_id: data.user.user_id,
          login: data.user.login,
          provider: "guest",
          avatar_url: null,
        },
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

  // Logout — hit backend to clear cookie + purge server session entry
  const logout = useCallback(async () => {
    try {
      await fetch(`${API_URL}/api/v1/auth/logout`, {
        method: "POST",
        credentials: "include",
      });
    } catch (e) {
      // ignore network errors — still clear local state
    }
    setState({ user: null, isLoading: false, isAuthenticated: false });
  }, []);

  // Auth headers are now trivial — no tokens live on the client.
  // Kept as a no-op for backwards compatibility with existing call sites.
  const authHeaders = useCallback((): HeadersInit => {
    return { "Content-Type": "application/json" };
  }, []);

  // Convenience wrapper: prepends API_URL, always sends the cookie.
  const apiFetch = useCallback(
    (path: string, init?: RequestInit): Promise<Response> => {
      const url = path.startsWith("http") ? path : `${API_URL}${path}`;
      return fetch(url, { ...init, credentials: "include" });
    },
    []
  );

  const value: AuthContextValue = {
    ...state,
    loginWithGitHub,
    loginAsGuest,
    logout,
    authHeaders,
    apiFetch,
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
