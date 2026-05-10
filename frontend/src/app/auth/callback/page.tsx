"use client";

import React, { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import NeuralLoader from "@/components/NeuralLoader";

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
          setTimeout(() => router.push("/"), 2000);
        }
      });
    } else {
      setStatus("Auth context not ready. Redirecting...");
      setTimeout(() => router.push("/"), 1000);
    }
  }, [searchParams, router]);

  return (
    <NeuralLoader status={status} detail="Securing your GitHub session" />
  );
}

export default function AuthCallbackPage() {
  return (
    <Suspense fallback={<NeuralLoader status="Preparing Cortex" />}>
      <CallbackHandler />
    </Suspense>
  );
}
