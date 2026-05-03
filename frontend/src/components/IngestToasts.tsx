"use client";

import React from "react";
import { CheckCircle2, AlertTriangle, LoaderCircle } from "lucide-react";

type IngestToastsProps = {
  events: Array<{
    id: string;
    stage: string;
    message: string;
    state: "running" | "done" | "error";
  }>;
};

export default function IngestToasts({ events }: IngestToastsProps) {
  if (events.length === 0) return null;

  return (
    <div
      style={{
        position: "fixed",
        right: 16,
        bottom: 16,
        zIndex: 85,
        display: "flex",
        flexDirection: "column",
        gap: 8,
        width: "min(390px, calc(100vw - 24px))",
      }}
    >
      {events.slice(-6).map((event) => (
        <article
          key={event.id}
          style={{
            border: "1px solid var(--line)",
            borderRadius: 10,
            background: "rgba(20,24,18,0.9)",
            backdropFilter: "blur(10px)",
            padding: "10px 12px",
            boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
            display: "grid",
            gap: 4,
          }}
        >
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12 }}>
            {event.state === "done" ? (
              <CheckCircle2 size={14} color="var(--accent)" />
            ) : event.state === "error" ? (
              <AlertTriangle size={14} color="var(--warn)" />
            ) : (
              <LoaderCircle size={14} className="spinner" color="var(--accent)" />
            )}
            <strong style={{ textTransform: "capitalize" }}>{event.stage.replaceAll("_", " ")}</strong>
          </div>
          <p style={{ color: "var(--muted)", fontSize: 12 }}>{event.message}</p>
        </article>
      ))}
    </div>
  );
}
