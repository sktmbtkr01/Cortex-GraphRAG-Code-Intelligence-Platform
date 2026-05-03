"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

function CallbackHandler() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState("Processing GitHub login...");
  const didSubmitRef = useRef(false);

  useEffect(() => {
    if (didSubmitRef.current) {
      return;
    }

    const code = searchParams.get("code");
    if (!code) {
      setStatus("Error: No authorization code received from GitHub.");
      return;
    }
    didSubmitRef.current = true;

    const handleCallback = (globalThis as any).__cortex_handle_github_callback;
    if (handleCallback) {
      handleCallback(code).then((success: boolean) => {
        if (success) {
          setStatus("Login successful! Redirecting...");
          setTimeout(() => router.push("/repos"), 500);
        } else {
          setStatus("Login failed. Please try again.");
          setTimeout(() => router.push("/login"), 2000);
        }
      });
    } else {
      setStatus("Auth context not ready. Redirecting to login...");
      setTimeout(() => router.push("/login"), 1000);
    }
  }, [searchParams, router]);

  return (
    <section className="login-page">
      <div className="login-container" style={{ textAlign: "center" }}>
        <span className="brand-mark" style={{ width: 56, height: 56, fontSize: 22, margin: "0 auto" }}>Cx</span>
        <h2 style={{ marginTop: 24 }}>{status}</h2>
        <div style={{ marginTop: 24 }}>
          <span className="spinner" style={{ display: "inline-block", width: 24, height: 24, border: "2px solid var(--line)", borderTopColor: "var(--accent)", borderRadius: "50%" }} />
        </div>
      </div>
    </section>
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<div style={{ padding: 44, color: "var(--muted)" }}>Loading...</div>}>
      <CallbackHandler />
    </Suspense>
  );
}
