"use client";

import React from "react";
import { Activity, Camera, RefreshCw, Trash2, GitBranch, Lock, Globe, Star } from "lucide-react";
import QuickPrompts from "@/components/QuickPrompts";

type RepoCardProps = {
  repo: string;
  branch: string;
  commitSha?: string | null;
  isPrivate: boolean;
  ingestionStatus?: string;
  language?: string | null;
  stars?: number;
  onSnapshot: (repo: string, branch: string) => void;
  onHealthCheck: (repo: string, branch: string) => void;
  onUpdate: (repo: string, branch: string) => void;
  onDelete: (repo: string, branch: string) => void;
};

export default function RepoCard({
  repo,
  branch,
  commitSha,
  isPrivate,
  ingestionStatus = "ready",
  language,
  stars,
  onSnapshot,
  onHealthCheck,
  onUpdate,
  onDelete,
}: RepoCardProps) {
  const status = (ingestionStatus || "ready").toLowerCase();
  const statusStyles =
    status === "processing" || status === "updating"
      ? { label: status === "updating" ? "Updating" : "Processing", color: "#f3b35f", border: "rgba(243,179,95,0.35)", bg: "rgba(243,179,95,0.12)" }
      : status === "failed" || status === "update_failed"
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
              <span>@ {branch}</span>
              {commitSha ? <span>{commitSha.slice(0, 7)}</span> : null}
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
            onClick={() => onSnapshot(repo, branch)}
            style={{ background: "var(--panel)", border: "1px solid var(--line)", padding: "8px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}
            title="Architecture Snapshot"
          >
            <Camera size={14} /> <span style={{ fontSize: 12 }}>Snapshot</span>
          </button>
          <button
            onClick={() => onUpdate(repo, branch)}
            style={{ background: "var(--panel)", border: "1px solid var(--line)", padding: "8px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}
            title="Check for Updates"
          >
            <RefreshCw size={14} /> <span style={{ fontSize: 12 }}>Update</span>
          </button>
          <button
            onClick={() => onHealthCheck(repo, branch)}
            style={{ background: "rgba(243, 179, 95, 0.1)", border: "1px solid var(--warn)", color: "var(--warn)", padding: "8px 10px", display: "inline-flex", alignItems: "center", gap: 6 }}
            title="Run Repository Health Check"
          >
            <Activity size={14} /> <span style={{ fontSize: 12 }}>Health</span>
          </button>
          <button
            onClick={() => onDelete(repo, branch)}
            style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--warn)", padding: "8px 10px" }}
            title="Delete Repo"
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div>
        <p style={{ color: "var(--muted)", fontSize: 12, marginBottom: 8 }}>Quick prompts</p>
        <QuickPrompts repo={repo} branch={branch} />
      </div>
    </article>
  );
}
