"use client";

import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, GitBranch as GitHubIcon, Sparkles } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import MarkdownMessage from "@/components/MarkdownMessage";
import HealthCheckReport from "@/components/HealthCheckReport";
import RepoCard from "@/components/RepoCard";
import Drawer from "@/components/Drawer";
import IngestToasts from "@/components/IngestToasts";
import { openIngestEventStream, type IngestStreamEvent } from "@/app/utils/sse";

interface Repo {
  repo: string;
  branch: string;
  commit_sha?: string | null;
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

interface GitHubBranch {
  name: string;
  commit_sha?: string | null;
}

export default function ReposPage() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const { authHeaders } = useAuth();

  const [repos, setRepos] = useState<Repo[]>([]);
  const [myRepos, setMyRepos] = useState<GitHubRepo[]>([]);
  const [myReposWarning, setMyReposWarning] = useState("");
  const [selectedMyRepo, setSelectedMyRepo] = useState("");
  const [branches, setBranches] = useState<GitHubBranch[]>([]);
  const [selectedBranch, setSelectedBranch] = useState("main");

  const [loading, setLoading] = useState(false);
  const [ingestStatus, setIngestStatus] = useState("");
  const [repoLoadWarning, setRepoLoadWarning] = useState("");

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
      if (Array.isArray(data)) {
        setRepos(data);
        setRepoLoadWarning("");
      } else {
        console.warn("Unexpected repos response", data);
        setRepos([]);
        setRepoLoadWarning("Could not load indexed repositories. Check backend auth/session and API logs.");
      }
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
      const repoItems = Array.isArray(data) ? data : [];
      setMyRepos(repoItems);
      setMyReposWarning(repoItems?.[0]?.warning || "");
      if (repoItems.length > 0) {
        setSelectedMyRepo(repoItems[0].full_name);
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

  useEffect(() => {
    const repoToLoad = resolveIngestRepo();
    if (!repoToLoad) {
      setBranches([]);
      setSelectedBranch("main");
      return;
    }

    const meta = myRepoMetaByName[repoToLoad];
    const defaultBranch = meta?.default_branch || "main";
    setSelectedBranch(defaultBranch);

    const [owner, name] = repoToLoad.split("/");
    if (!owner || !name) return;

    fetch(`${API_URL}/api/v1/github/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/branches`, {
      headers: authHeaders(),
      credentials: "include",
    })
      .then((res) => (res.ok ? res.json() : []))
      .then((data) => {
        const loaded = Array.isArray(data) ? data : [];
        setBranches(loaded);
        if (loaded.some((b: GitHubBranch) => b.name === defaultBranch)) {
          setSelectedBranch(defaultBranch);
        } else if (loaded[0]?.name) {
          setSelectedBranch(loaded[0].name);
        }
      })
      .catch(() => setBranches([]));
  }, [selectedMyRepo, myRepoMetaByName, API_URL, authHeaders]);

  const pushToast = (event: IngestStreamEvent) => {
    const toast = {
      id: `${event.stage}-${event.state}`,
      stage: event.stage,
      message: event.message,
      state: event.state === "lost" ? "error" as const : event.state === "queued" ? "running" as const : event.state,
    };

    setToastEvents((prev) => {
      if (toast.state === "done" || toast.state === "error") {
        return [toast];
      }

      const next = [...prev.filter((item) => item.stage !== toast.stage), toast];
      return next.filter((item) => item.state === "running").slice(-4);
    });
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
      setTimeout(() => setToastEvents([]), 4500);
    }

    if (event.state === "lost") {
      setLoading(false);
      ingestActiveRef.current = false;
      setIngestStatus(event.message);
      closeStream();
      closePoll();
      setTimeout(() => setToastEvents([]), 6500);
      return;
    }

    if (event.type === "error") {
      setLoading(false);
      ingestActiveRef.current = false;
      setIngestStatus(`Ingest failed: ${event.message}`);
      closeStream();
      closePoll();
      setTimeout(() => setToastEvents([]), 6500);
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
    return selectedMyRepo || null;
  };

  const handleIngest = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    const repoToIngest = resolveIngestRepo();
    if (!repoToIngest) {
      alert("Select a repository first.");
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
          branch: selectedBranch || "main",
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

  const handleDelete = async (repoName: string, branchName: string) => {
    if (!confirm(`Are you sure you want to delete ${repoName} @ ${branchName} from the index?`)) return;

    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}?branch=${encodeURIComponent(branchName)}`, {
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

  const handleViewSnapshot = async (repoName: string, branchName: string) => {
    setDrawerTitle(`Architecture Snapshot: ${repoName} @ ${branchName}`);
    setDrawerContent("");
    setDrawerLoading(true);
    setDrawerOpen(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/snapshot?branch=${encodeURIComponent(branchName)}`, { headers: authHeaders(), credentials: "include" });
      const data = await res.json();
      if (res.ok) setDrawerContent(data.snapshot);
      else setDrawerContent(`Error: ${data.detail}`);
    } catch (e) {
      setDrawerContent("Failed to connect to backend.");
    } finally {
      setDrawerLoading(false);
    }
  };

  const handleUpdate = async (repoName: string, branchName: string) => {
    if (!confirm(`Check for updates and refresh ${repoName} @ ${branchName} if needed?`)) return;

    setLoading(true);
    ingestActiveRef.current = true;
    setIngestStatus(`Checking updates for ${repoName} @ ${branchName}...`);

    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/branches/${encodeURIComponent(branchName)}/update`, {
        method: "POST",
        credentials: "include",
        headers: authHeaders(),
      });
      const data = await res.json();
      if (!res.ok) {
        alert("Error: " + data.detail);
        setLoading(false);
        ingestActiveRef.current = false;
        return;
      }

      if (data.status === "up_to_date") {
        setIngestStatus(`${repoName} @ ${branchName} is already up to date.`);
        setLoading(false);
        ingestActiveRef.current = false;
        void fetchRepos();
        return;
      }

      setIngestStatus(`Update queued: ${data.job_id}`);
      closeStream();
      closePoll();
      ingestCursorRef.current = 0;
      ingestSseSeenEventRef.current = false;
      const es = openIngestEventStream(
        API_URL,
        data.job_id,
        (event) => {
          ingestSseSeenEventRef.current = true;
          handleIngestEvent(event, repoName);
        },
        () => {
          if (ingestActiveRef.current) {
            closeStream();
            startPollingFallback(data.job_id, repoName);
          }
        },
      );

      ingestStreamRef.current = es;
      ingestWatchdogRef.current = setTimeout(() => {
        if (ingestActiveRef.current && !ingestSseSeenEventRef.current) {
          closeStream();
          startPollingFallback(data.job_id, repoName);
        }
      }, 3000);
    } catch {
      setIngestStatus("Failed to check updates. Check backend logs.");
      setLoading(false);
      ingestActiveRef.current = false;
    }
  };

  const handleRunHealthCheck = async (repoName: string, branchName: string) => {
    setDrawerTitle(`Health Check: ${repoName} @ ${branchName}`);
    setDrawerContent("");
    setDrawerLoading(true);
    setDrawerOpen(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/health-check?branch=${encodeURIComponent(branchName)}`, {
        method: "POST",
        credentials: "include",
        headers: authHeaders()
      });
      const data = await res.json();
      if (res.ok) setDrawerContent(data.report);
      else setDrawerContent(`Error: ${data.detail}`);
    } catch (e) {
      setDrawerContent("Failed to run repository health check.");
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
              <GitHubIcon size={14} /> My Repositories
            </button>
          </div>

          <form className="form-row" onSubmit={handleIngest} style={{ padding: 0, border: "none", flexDirection: "column", alignItems: "stretch" }}>
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

            <select
              value={selectedBranch}
              onChange={(e) => setSelectedBranch(e.target.value)}
              aria-label="Repository branch"
              disabled={loading}
            >
              {branches.length === 0 ? (
                <option value={selectedBranch || "main"}>{selectedBranch || "main"}</option>
              ) : (
                branches.map((branch) => (
                  <option key={branch.name} value={branch.name}>
                    {branch.name}
                  </option>
                ))
              )}
            </select>

            <button type="submit" disabled={loading || !selectedMyRepo}>
              {loading ? <RefreshCw className="spinner" size={16} /> : "Ingest"}
            </button>
          </form>

          {ingestStatus && (
            <div style={{ marginTop: 16, padding: 12, background: "var(--panel-strong)", borderRadius: 6, fontSize: 14 }}>
              {ingestStatus}
            </div>
          )}
          {myReposWarning && (
            <p style={{ marginTop: 10, color: "var(--warn)", fontSize: 12 }}>{myReposWarning}</p>
          )}
        </article>

        <article className="panel">
          <h2>Indexed Repos</h2>
          {repoLoadWarning && (
            <p style={{ color: "var(--warn)", fontSize: 12, marginBottom: 10 }}>{repoLoadWarning}</p>
          )}
          {repos.length === 0 ? (
            <div className="empty-state">No repositories indexed yet.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {repos.map(r => (
                <RepoCard
                  key={`${r.repo}@${r.branch}`}
                  repo={r.repo}
                  branch={r.branch || "main"}
                  commitSha={r.commit_sha}
                  isPrivate={r.is_private}
                  ingestionStatus={r.ingestion_status}
                  language={myRepoMetaByName[r.repo]?.language ?? null}
                  stars={myRepoMetaByName[r.repo]?.stars ?? 0}
                  onSnapshot={handleViewSnapshot}
                  onHealthCheck={handleRunHealthCheck}
                  onUpdate={handleUpdate}
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
            ) : drawerTitle.startsWith("Health Check:") ? (
                <HealthCheckReport content={drawerContent} />
            ) : (
              <MarkdownMessage content={drawerContent} />
            )}
          </div>
        </article>
      </Drawer>
    </section>
  );
}
