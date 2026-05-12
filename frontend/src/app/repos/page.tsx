"use client";

import React, { useEffect, useRef, useState } from "react";
import { RefreshCw, GitBranch as GitHubIcon, Sparkles } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import MarkdownMessage from "@/components/MarkdownMessage";
import HealthCheckReport from "@/components/HealthCheckReport";
import RepoCard from "@/components/RepoCard";
import Drawer from "@/components/Drawer";
import GlobalBrainBar from "@/components/GlobalBrainBar";
import SearchableSelect from "@/components/ui/searchable-select";
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

function simplifyIngestStage(stage: string, message = "") {
  const text = `${stage} ${message}`.toLowerCase();
  if (stage === "fetching_tree") return "fetching metadata";
  if (stage === "clone_start") return "cloning";
  if (stage === "clone_done") return "files selected";
  if (stage === "embedding") return "embedding";
  if (stage === "embedding_batch") return "embedding";
  if (stage === "upserting") return "upserting";
  if (stage === "qdrant_upsert") return "upserting";
  if (stage === "graph_building") return "building graph";
  if (stage === "graph_write") return "building graph";
  if (stage === "file_filtering") return "filtering files";
  if (stage === "processing_batch") return "processing files";
  if (stage === "cleanup") return "cleanup";
  if (stage === "timing_summary") return "timings";
  if (stage === "done") return "complete";
  if (text.includes("embed")) return "embedding";
  if (text.includes("upsert") || text.includes("qdrant")) return "upserting";
  if (text.includes("clone")) return "cloning";
  if (text.includes("chunk")) return "chunking";
  if (text.includes("graph") || text.includes("neo4j")) return "building graph";
  if (text.includes("snapshot")) return "snapshot";
  if (text.includes("fetch") || text.includes("github")) return "fetching files";
  if (text.includes("queue") || text.includes("start")) return "queued";
  if (text.includes("done") || text.includes("complete")) return "complete";
  return stage.replaceAll("_", " ");
}

function simplifyIngestMessage(message: string) {
  return message
    .replace(/\b\d+\s*\/\s*\d+\b/g, "")
    .replace(/\b\d+%\b/g, "")
    .replace(/\s{2,}/g, " ")
    .replace(/\s+([,.])/g, "$1")
    .trim();
}

function formatIngestTimings(timings?: Record<string, number>) {
  if (!timings) return "";

  const labels: Record<string, string> = {
    clone_ms: "clone",
    tree_fetch_ms: "tree",
    filter_ms: "filter",
    file_fetch_ms: "fetch",
    file_walk_ms: "walk",
    parse_chunk_ms: "parse/chunk",
    graph_write_ms: "graph",
    embedding_ms: "embed",
    sparse_vector_ms: "sparse",
    qdrant_upsert_ms: "upsert",
    snapshot_ms: "snapshot",
    total_ms: "total",
  };

  return Object.entries(timings)
    .filter(([, value]) => typeof value === "number")
    .sort(([left], [right]) => (left === "total_ms" ? 1 : right === "total_ms" ? -1 : 0))
    .map(([key, value]) => `${labels[key] || key.replace(/_ms$/, "")}: ${(value / 1000).toFixed(1)}s`)
    .join(" · ");
}

function upsertIngestEvent(
  events: Array<{ id: string; stage: string; message: string; state: "running" | "done" | "error" }>,
  next: { id: string; stage: string; message: string; state: "running" | "done" | "error" },
) {
  return [...events.filter((item) => item.stage !== next.stage), next];
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

  const repoOptions = React.useMemo(() => {
    return myRepos.map((repo) => ({
      value: repo.full_name,
      label: repo.full_name,
      meta: `${repo.private ? "Private" : "Public"}${repo.language ? ` · ${repo.language}` : ""} · ${repo.stars} stars`,
    }));
  }, [myRepos]);

  const branchOptions = React.useMemo(() => {
    if (branches.length === 0) {
      return [{ value: selectedBranch || "main", label: selectedBranch || "main" }];
    }
    return branches.map((branch) => ({
      value: branch.name,
      label: branch.name,
      meta: branch.commit_sha ? branch.commit_sha.slice(0, 7) : undefined,
    }));
  }, [branches, selectedBranch]);

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
    const stage = simplifyIngestStage(event.stage, event.message);
    const timingSummary = event.type === "done" ? formatIngestTimings(event.stats?.timings_ms) : "";
    const toast = {
      id: `${stage}-${event.state}`,
      stage,
      message: timingSummary || simplifyIngestMessage(event.message),
      state: event.state === "lost" ? "error" as const : event.state === "queued" ? "running" as const : event.state,
    };

    setToastEvents((prev) => {
      if (toast.state === "done" || toast.state === "error") {
        return upsertIngestEvent(prev, toast);
      }

      return upsertIngestEvent(prev, toast).slice(-6);
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

  const pushIngestConsoleEvent = (
    stage: string,
    message: string,
    state: "running" | "done" | "error" = "running",
  ) => {
    setToastEvents((events) =>
      upsertIngestEvent(events, {
        id: `${stage}-${Date.now()}`,
        stage: simplifyIngestStage(stage, message),
        message: simplifyIngestMessage(message),
        state,
      }),
    );
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
      const data = await res.json().catch(() => ({}));
      if (res.ok && data.status === "success") {
        void fetchRepos();
      } else if (res.ok) {
        void fetchRepos();
        alert(`Repository delete was incomplete. Graph remaining: ${data.graph_remaining ?? "unknown"}, Qdrant remaining: ${data.qdrant_remaining ?? "unknown"}.`);
      } else {
        alert(data.detail || "Failed to delete repository.");
      }
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
        const message = data.detail || "Failed to check for repository updates.";
        setIngestStatus(message);
        pushIngestConsoleEvent("update failed", message, "error");
        setLoading(false);
        ingestActiveRef.current = false;
        return;
      }

      if (data.status === "up_to_date") {
        setIngestStatus(`${repoName} @ ${branchName} is already up to date.`);
        setToastEvents([]);
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

  const visibleIngestEvents = toastEvents.slice(-6);

  return (
    <section className="workspace repos-workspace">
      <header className="page-header repo-page-header">
        <h1>Repository Manager</h1>
      </header>

      <GlobalBrainBar />

      <div className="repo-manager-grid">
        <article className="panel repo-ingest-panel">
          <h2>Add Repository</h2>

          <div className="repo-source-pill">
            <button type="button" disabled={loading}>
              <GitHubIcon size={14} /> My Repositories
            </button>
          </div>

          <form className="repo-ingest-form" onSubmit={handleIngest}>
            <SearchableSelect
              label="Repository"
              value={selectedMyRepo}
              onChange={setSelectedMyRepo}
              options={repoOptions}
              placeholder="Select repository"
              emptyText="No repositories found."
              disabled={loading || myRepos.length === 0}
            />

            <SearchableSelect
              label="Branch"
              value={selectedBranch}
              onChange={setSelectedBranch}
              options={branchOptions}
              placeholder="Select branch"
              emptyText="No branches found."
              disabled={loading}
            />

            <button type="submit" disabled={loading || !selectedMyRepo}>
              {loading ? <RefreshCw className="spinner" size={16} /> : "Ingest"}
            </button>
          </form>

          {(ingestStatus || visibleIngestEvents.length > 0 || loading) && (
            <div className="ingest-console">
              <div className="ingest-animation" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <div className="ingest-console-header">
                <strong>{loading ? "Ingestion running" : "Ingestion status"}</strong>
                {ingestStatus && <small>{simplifyIngestMessage(ingestStatus)}</small>}
              </div>
              <div className="ingest-stage-list">
                {visibleIngestEvents.length > 0 ? (
                  visibleIngestEvents.map((event) => (
                    <div className={`ingest-stage ${event.state}`} key={event.id}>
                      <span />
                      <div>
                        <strong>{event.stage}</strong>
                        <p>{event.message || event.stage}</p>
                      </div>
                    </div>
                  ))
                ) : loading ? (
                  <div className="ingest-stage running">
                    <span />
                    <div>
                      <strong>queued</strong>
                      <p>Preparing repository ingest.</p>
                    </div>
                  </div>
                ) : null}
              </div>
            </div>
          )}
          {myReposWarning && (
            <p style={{ marginTop: 10, color: "var(--warn)", fontSize: 12 }}>{myReposWarning}</p>
          )}
        </article>

        <article className="panel repo-indexed-panel">
          <h2>Indexed Repos</h2>
          {repoLoadWarning && (
            <p style={{ color: "var(--warn)", fontSize: 12, marginBottom: 10 }}>{repoLoadWarning}</p>
          )}
          {repos.length === 0 ? (
            <div className="empty-state">No repositories indexed yet.</div>
          ) : (
            <div className="repo-card-stack">
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
