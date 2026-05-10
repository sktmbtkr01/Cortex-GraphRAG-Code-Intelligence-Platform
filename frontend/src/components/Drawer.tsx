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
          right: 18,
          top: 122,
          bottom: 18,
          height: "calc(100% - 140px)",
          width: "min(660px, calc(100vw - 36px))",
          border: "1px solid rgba(255,255,255,0.1)",
          borderRadius: 28,
          background: "rgba(8, 12, 10, 0.82)",
          backdropFilter: "blur(24px)",
          transform: open ? "translateX(0)" : "translateX(108%)",
          transition: "transform 260ms cubic-bezier(.2,.8,.2,1)",
          display: "grid",
          gridTemplateRows: "auto 1fr",
          boxShadow: "-20px 0 70px rgba(0,0,0,0.42)",
          overflow: "hidden",
        }}
      >
        <header
          style={{
            padding: "18px 20px",
            borderBottom: "1px solid rgba(255,255,255,0.08)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <strong style={{ fontSize: 15, letterSpacing: 0 }}>{title || "Details"}</strong>
          <button
            type="button"
            onClick={onClose}
            style={{
              minHeight: 30,
              padding: "0 8px",
              background: "rgba(255,255,255,0.04)",
              color: "var(--muted)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: 999,
            }}
            aria-label="Close drawer"
          >
            <X size={16} />
          </button>
        </header>

        <div style={{ overflow: "auto", padding: "18px 20px" }}>{children}</div>
      </aside>
    </div>
  );
}
