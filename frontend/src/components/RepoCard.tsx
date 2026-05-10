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
    <article className="repo-card">
      <div className="repo-card-main">
        <div className="repo-card-identity">
          <GitBranch size={18} color="var(--accent)" />
          <div>
            <strong>{repo}</strong>
            <span className="repo-card-meta">
              <span>@ {branch}</span>
              {commitSha ? <span>{commitSha.slice(0, 7)}</span> : null}
              <span>{isPrivate ? <Lock size={12} /> : <Globe size={12} />}{isPrivate ? "Private" : "Public"}</span>
              {language ? <span>{language}</span> : null}
              <span><Star size={11} /> {stars ?? 0}</span>
              <span
                className="repo-status-pill"
                style={{
                  borderColor: statusStyles.border,
                  color: statusStyles.color,
                  background: statusStyles.bg,
                }}
              >
                {statusStyles.label}
              </span>
            </span>
          </div>
        </div>

        <div className="repo-card-actions">
          <button onClick={() => onSnapshot(repo, branch)} title="Architecture Snapshot">
            <Camera size={14} /> <span>Snapshot</span>
          </button>
          <button onClick={() => onUpdate(repo, branch)} title="Check for Updates">
            <RefreshCw size={14} /> <span>Update</span>
          </button>
          <button className="repo-card-health" onClick={() => onHealthCheck(repo, branch)} title="Run Repository Health Check">
            <Activity size={14} /> <span>Health</span>
          </button>
          <button className="repo-card-delete" onClick={() => onDelete(repo, branch)} title="Delete Repo">
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      <div className="repo-card-prompts">
        <p>Quick prompts</p>
        <QuickPrompts repo={repo} branch={branch} />
      </div>
    </article>
  );
}
