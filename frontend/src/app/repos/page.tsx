"use client";

import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, GitBranch as GitHubIcon, Link2, Sparkles } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import MarkdownMessage from "@/components/MarkdownMessage";
import RepoCard from "@/components/RepoCard";
import { parseRepoUrl } from "@/app/utils/parseRepoUrl";
import Drawer from "@/components/Drawer";
import IngestToasts from "@/components/IngestToasts";
import { openIngestEventStream, type IngestStreamEvent } from "@/app/utils/sse";

interface Repo {
  repo: string;
  is_private: boolean;
  ingestion_status?: string;
}

interface GitHubRepo {
  name: string;
  full_name: string;
  private: boolean;
  language?: string | null;
  stars: number;
  default_branch: string;
  warning?: string;
}

export default function ReposPage() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const { authHeaders } = useAuth();

  const [mode, setMode] = useState<"my" | "url">("my");

  const [repos, setRepos] = useState<Repo[]>([]);
  const [myRepos, setMyRepos] = useState<GitHubRepo[]>([]);
  const [myReposWarning, setMyReposWarning] = useState("");
  const [selectedMyRepo, setSelectedMyRepo] = useState("");
  const [repoUrl, setRepoUrl] = useState("");

  const [loading, setLoading] = useState(false);
  const [ingestStatus, setIngestStatus] = useState("");

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTitle, setDrawerTitle] = useState("");
  const [drawerContent, setDrawerContent] = useState("");
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [toastEvents, setToastEvents] = useState<Array<{ id: string; stage: string; message: string; state: "running" | "done" | "error" }>>([]);

  const ingestStreamRef = useRef<EventSource | null>(null);
  const ingestPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const ingestWatchdogRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ingestCursorRef = useRef(0);
  const ingestActiveRef = useRef(false);
  const ingestSseSeenEventRef = useRef(false);

  const myRepoMetaByName = React.useMemo(() => {
    return myRepos.reduce<Record<string, GitHubRepo>>((acc, item) => {
      acc[item.full_name] = item;
      return acc;
    }, {});
  }, [myRepos]);

  const fetchRepos = async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/repos`, { headers: authHeaders(), credentials: "include" });
      const data = await res.json();
      setRepos(data);
    } catch (e) {
      console.error("Failed to fetch repos", e);
    }
  };

  const fetchMyRepos = async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/github/my-repos`, {
        headers: authHeaders(),
        credentials: "include",
      });
      if (!res.ok) {
        setMyRepos([]);
        setMyReposWarning("");
        return;
      }
      const data = await res.json();
      setMyRepos(data);
      setMyReposWarning(data?.[0]?.warning || "");
      if (data.length > 0) {
        setSelectedMyRepo(data[0].full_name);
      }
    } catch (e) {
      console.error("Failed to fetch GitHub repos", e);
      setMyRepos([]);
      setMyReposWarning("");
    }
  };

  useEffect(() => {
    void fetchRepos();
    void fetchMyRepos();

    return () => {
      closeStream();
      closePoll();
      if (ingestWatchdogRef.current) {
        clearTimeout(ingestWatchdogRef.current);
        ingestWatchdogRef.current = null;
      }
    };
  }, []);

  const pushToast = (event: IngestStreamEvent) => {
    setToastEvents((prev) => [
      ...prev,
      {
        id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        stage: event.stage,
        message: event.message,
        state: event.state === "lost" ? "error" : event.state === "queued" ? "running" : event.state,
      },
    ]);
  };

  const closeStream = () => {
    if (ingestStreamRef.current) {
      ingestStreamRef.current.close();
      ingestStreamRef.current = null;
    }
    if (ingestWatchdogRef.current) {
      clearTimeout(ingestWatchdogRef.current);
      ingestWatchdogRef.current = null;
    }
  };

  const closePoll = () => {
    if (ingestPollRef.current) {
      clearInterval(ingestPollRef.current);
      ingestPollRef.current = null;
    }
  };

  const handleIngestEvent = (event: IngestStreamEvent, repoFallback: string) => {
    pushToast(event);
    if (event.state === "queued" || event.state === "running") {
      setIngestStatus(event.message);
    }

    if (event.type === "done") {
      setLoading(false);
      ingestActiveRef.current = false;
      setIngestStatus("Ingestion complete");
      setDrawerTitle(`Architecture Snapshot: ${event.repo || repoFallback}`);
      setDrawerContent(event.snapshot || "Snapshot generated.");
      setDrawerOpen(true);
      void fetchRepos();
      closeStream();
      closePoll();
    }

    if (event.state === "lost") {
      setLoading(false);
      ingestActiveRef.current = false;
      setIngestStatus(event.message);
      closeStream();
      closePoll();
      return;
    }

    if (event.type === "error") {
      setLoading(false);
      ingestActiveRef.current = false;
      setIngestStatus(`Ingest failed: ${event.message}`);
      closeStream();
      closePoll();
    }
  };

  const startPollingFallback = (jobId: string, repoFallback: string) => {
    closePoll();
    ingestCursorRef.current = 0;
    setIngestStatus("Realtime stream unavailable. Switching to polling updates...");

    ingestPollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/ingest/jobs/${encodeURIComponent(jobId)}?cursor=${ingestCursorRef.current}`, {
          credentials: "include",
          headers: authHeaders(),
        });
        if (!res.ok) {
          return;
        }

        const data = await res.json();
        ingestCursorRef.current = data.cursor ?? ingestCursorRef.current;
        const events = Array.isArray(data.events) ? (data.events as IngestStreamEvent[]) : [];
        for (const event of events) {
          handleIngestEvent(event, repoFallback);
        }

        if (data.done) {
          closePoll();
        }
      } catch {
        // Keep polling through transient network failures.
      }
    }, 2000);
  };

  const resolveIngestRepo = (): string | null => {
    if (mode === "my") {
      return selectedMyRepo || null;
    }
    return parseRepoUrl(repoUrl);
  };

  const handleIngest = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    const repoToIngest = resolveIngestRepo();
    if (!repoToIngest) {
      alert(mode === "my" ? "Select a repository first." : "Enter a valid GitHub repo URL.");
      return;
    }

    setLoading(true);
    ingestActiveRef.current = true;
    setIngestStatus(`Starting ingest job for ${repoToIngest}...`);
    try {
      const res = await fetch(`${API_URL}/api/v1/ingest`, {
        method: "POST",
        credentials: "include",
        headers: authHeaders(),
        body: JSON.stringify({
          repo: repoToIngest,
          branch: "main",
          include_issues: false,
          include_prs: false,
          include_commits: false,
          max_commits: 100,
        }),
      });
      const data = await res.json();
      if (!res.ok) alert("Error: " + data.detail);
      else {
        setIngestStatus(`Job queued: ${data.job_id}`);
        setRepoUrl("");

        closeStream();
        closePoll();
        ingestCursorRef.current = 0;
        ingestSseSeenEventRef.current = false;
        const es = openIngestEventStream(
          API_URL,
          data.job_id,
          (event) => {
            ingestSseSeenEventRef.current = true;
            handleIngestEvent(event, repoToIngest);
          },
          () => {
            if (ingestActiveRef.current) {
              closeStream();
              startPollingFallback(data.job_id, repoToIngest);
            }
          },
        );

        ingestStreamRef.current = es;
        ingestWatchdogRef.current = setTimeout(() => {
          if (ingestActiveRef.current && !ingestSseSeenEventRef.current) {
            closeStream();
            startPollingFallback(data.job_id, repoToIngest);
          }
        }, 3000);
      }
    } catch (e) {
      setIngestStatus("Failed to ingest repository. Check backend logs.");
      closeStream();
      closePoll();
      setLoading(false);
      ingestActiveRef.current = false;
    } finally {
      // Keep loading=true while ingest stream is active; it is released on done/error.
    }
  };

  const handleDelete = async (repoName: string) => {
    if (!confirm(`Are you sure you want to delete ${repoName} from the index?`)) return;

    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}`, {
        method: "DELETE",
        credentials: "include",
        headers: authHeaders(),
      });
      if (res.ok) void fetchRepos();
      else alert("Failed to delete repository.");
    } catch (e) {
      alert("Error reaching backend.");
    }
  };

  const handleViewSnapshot = async (repoName: string) => {
    setDrawerTitle(`Architecture Snapshot: ${repoName}`);
    setDrawerContent("");
    setDrawerLoading(true);
    setDrawerOpen(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/snapshot`, { headers: authHeaders(), credentials: "include" });
      const data = await res.json();
      if (res.ok) setDrawerContent(data.snapshot);
      else setDrawerContent(`Error: ${data.detail}`);
    } catch (e) {
      setDrawerContent("Failed to connect to backend.");
    } finally {
      setDrawerLoading(false);
    }
  };

  const handleRunAudit = async (repoName: string) => {
    setDrawerTitle(`Security Audit: ${repoName}`);
    setDrawerContent("");
    setDrawerLoading(true);
    setDrawerOpen(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/audit`, {
        method: "POST",
        credentials: "include",
        headers: authHeaders()
      });
      const data = await res.json();
      if (res.ok) setDrawerContent(data.report);
      else setDrawerContent(`Error: ${data.detail}`);
    } catch (e) {
      setDrawerContent("Failed to run security audit.");
    } finally {
      setDrawerLoading(false);
    }
  };

  return (
    <section className="workspace">
      <header className="page-header">
        <p>Repositories</p>
        <h1>Repository Manager</h1>
      </header>

      <div className="panel-grid" style={{ marginTop: 24 }}>
        <article className="panel">
          <h2>Add Repository</h2>

          <div style={{ display: "inline-flex", gap: 8, marginTop: 12, marginBottom: 16 }}>
            <button type="button" disabled={loading}>
              {mode === "my" ? <GitHubIcon size={14} /> : <Link2 size={14} />} {mode === "my" ? "My Repositories" : "Public URL"}
            </button>
            <button
              type="button"
              onClick={() => setMode(mode === "my" ? "url" : "my")}
              style={{ background: "var(--panel)", color: "var(--foreground)" }}
            >
              Switch to {mode === "my" ? "Public URL" : "My Repositories"}
            </button>
          </div>

          <form className="form-row" onSubmit={handleIngest} style={{ padding: 0, border: "none", flexDirection: "column", alignItems: "stretch" }}>
            {mode === "my" ? (
              <select
                value={selectedMyRepo}
                onChange={(e) => setSelectedMyRepo(e.target.value)}
                aria-label="My repositories"
                disabled={loading || myRepos.length === 0}
              >
                {myRepos.length === 0 ? (
                  <option value="">No GitHub repos available</option>
                ) : (
                  myRepos.map((repo) => (
                    <option key={repo.full_name} value={repo.full_name}>
                      {repo.full_name} {repo.private ? "(private)" : "(public)"}
                    </option>
                  ))
                )}
              </select>
            ) : (
              <input
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                aria-label="GitHub URL"
                placeholder="https://github.com/vercel/next.js"
                disabled={loading}
              />
            )}

            <button type="submit" disabled={loading || (mode === "my" ? !selectedMyRepo : !repoUrl.trim())}>
              {loading ? <RefreshCw className="spinner" size={16} /> : "Ingest"}
            </button>
          </form>

          {ingestStatus && (
            <div style={{ marginTop: 16, padding: 12, background: "var(--panel-strong)", borderRadius: 6, fontSize: 14 }}>
              {ingestStatus}
            </div>
          )}
          {myReposWarning && mode === "my" && (
            <p style={{ marginTop: 10, color: "var(--warn)", fontSize: 12 }}>{myReposWarning}</p>
          )}
          <p style={{ marginTop: 10, color: "var(--muted)", fontSize: 12 }}>
            Tip: GitHub dropdown is available for OAuth users. Guest mode can still ingest via Public URL.
          </p>
        </article>

        <article className="panel">
          <h2>Indexed Repos</h2>
          {repos.length === 0 ? (
            <div className="empty-state">No repositories indexed yet.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {repos.map(r => (
                <RepoCard
                  key={r.repo}
                  repo={r.repo}
                  isPrivate={r.is_private}
                  ingestionStatus={r.ingestion_status}
                  language={myRepoMetaByName[r.repo]?.language ?? null}
                  stars={myRepoMetaByName[r.repo]?.stars ?? 0}
                  onSnapshot={handleViewSnapshot}
                  onAudit={handleRunAudit}
                  onDelete={handleDelete}
                />
              ))}
            </div>
          )}
        </article>
      </div>

      <IngestToasts events={toastEvents} />

      <Drawer open={drawerOpen} onClose={() => setDrawerOpen(false)} title={drawerTitle || "Details"}>
        <article>
          <h3 style={{ display: "inline-flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
            <Sparkles size={16} color="var(--accent)" /> {drawerTitle || "Result"}
          </h3>
          <div style={{ minHeight: 80 }}>
            {drawerLoading ? (
              <div style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--muted)" }}>
                <RefreshCw className="spinner" size={18} /> Processing...
              </div>
            ) : (
              <MarkdownMessage content={drawerContent} />
            )}
          </div>
        </article>
      </Drawer>
    </section>
  );
}
