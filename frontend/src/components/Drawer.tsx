"use client";

import React from "react";
import { X } from "lucide-react";

type DrawerProps = {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
};

export default function Drawer({ open, title, onClose, children }: DrawerProps) {
  return (
    <div
      aria-hidden={!open}
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 80,
        pointerEvents: open ? "auto" : "none",
      }}
    >
      <div
        onClick={onClose}
        style={{
          position: "absolute",
          inset: 0,
          background: open ? "rgba(0,0,0,0.45)" : "rgba(0,0,0,0)",
          transition: "background 180ms ease",
        }}
      />

      <aside
        role="dialog"
        aria-modal="true"
        style={{
          position: "absolute",
          right: 0,
          top: 0,
          height: "100%",
          width: "min(620px, 100vw)",
          borderLeft: "1px solid var(--line)",
          background: "rgba(24, 28, 22, 0.94)",
          backdropFilter: "blur(14px)",
          transform: open ? "translateX(0)" : "translateX(104%)",
          transition: "transform 220ms ease",
          display: "grid",
          gridTemplateRows: "auto 1fr",
          boxShadow: "-16px 0 48px rgba(0,0,0,0.35)",
        }}
      >
        <header
          style={{
            padding: "14px 16px",
            borderBottom: "1px solid var(--line)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <strong style={{ fontSize: 15 }}>{title || "Details"}</strong>
          <button
            type="button"
            onClick={onClose}
            style={{
              minHeight: 30,
              padding: "0 8px",
              background: "transparent",
              color: "var(--muted)",
              border: "1px solid var(--line)",
              borderRadius: 7,
            }}
            aria-label="Close drawer"
          >
            <X size={16} />
          </button>
        </header>

        <div style={{ overflow: "auto", padding: "16px 18px" }}>{children}</div>
      </aside>
    </div>
  );
}
