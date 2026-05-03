"use client";

import React from "react";
import { Camera, ShieldAlert, Trash2, GitBranch, Lock, Globe, Star } from "lucide-react";
import QuickPrompts from "@/components/QuickPrompts";

type RepoCardProps = {
  repo: string;
  isPrivate: boolean;
  ingestionStatus?: string;
  language?: string | null;
  stars?: number;
  onSnapshot: (repo: string) => void;
  onAudit: (repo: string) => void;
  onDelete: (repo: string) => void;
};

export default function RepoCard({
  repo,
  isPrivate,
  ingestionStatus = "ready",
  language,
  stars,
  onSnapshot,
  onAudit,
  onDelete,
}: RepoCardProps) {
  const status = (ingestionStatus || "ready").toLowerCase();
  const statusStyles =
    status === "processing"
      ? { label: "Processing", color: "#f3b35f", border: "rgba(243,179,95,0.35)", bg: "rgba(243,179,95,0.12)" }
      : status === "failed"
        ? { label: "Failed", color: "#ff6b6b", border: "rgba(255,107,107,0.35)", bg: "rgba(255,107,107,0.12)" }
        : { label: "Ready", color: "var(--accent)", border: "rgba(141,222,122,0.35)", bg: "rgba(141,222,122,0.12)" };

  return (
    <article
      style={{
        border: "1px solid var(--line)",
        background: "var(--panel-strong)",
        borderRadius: 8,
        padding: 14,
        display: "grid",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <GitBranch size={18} color="var(--accent)" />
          <div style={{ minWidth: 0 }}>
            <strong style={{ display: "block", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {repo}
            </strong>
            <span style={{ fontSize: 12, color: "var(--muted)", display: "inline-flex", alignItems: "center", gap: 8 }}>
              {isPrivate ? <><Lock size={12} /> Private</> : <><Globe size={12} /> Public</>}
              {language ? <span>• {language}</span> : null}
              <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                <Star size={11} /> {stars ?? 0}
              </span>
              <span
                style={{
                  marginLeft: 4,
                  padding: "1px 7px",
                  borderRadius: 999,
                  border: `1px solid ${statusStyles.border}`,
                  color: statusStyles.color,
                  background: statusStyles.bg,
                  fontSize: 11,
                  lineHeight: "16px",
                }}
              >
                {statusStyles.label}
              </span>
            </span>
          </div>
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => onSnapshot(repo)}
            style={{ background: "var(--panel)", border: "1px solid var(--line)", padding: "8px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}
            title="Architecture Snapshot"
          >
            <Camera size={14} /> <span style={{ fontSize: 12 }}>Snapshot</span>
          </button>
          <button
            onClick={() => onAudit(repo)}
            style={{ background: "rgba(243, 179, 95, 0.1)", border: "1px solid var(--warn)", color: "var(--warn)", padding: "8px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}
            title="Run Security Audit"
          >
            <ShieldAlert size={14} /> <span style={{ fontSize: 12 }}>Audit</span>
          </button>
          <button
            onClick={() => onDelete(repo)}
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--warn)", padding: "8px 10px" }}
            title="Delete Repo"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div>
        <p style={{ color: "var(--muted)", fontSize: 12, marginBottom: 8 }}>Quick prompts</p>
        <QuickPrompts repo={repo} />
      </div>
    </article>
  );
}
