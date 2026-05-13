"use client";

import React, { useState, useEffect, useRef } from "react";
import { useSearchParams } from "next/navigation";
import { Code2, FileText, GitBranch, LoaderCircle, MessageSquare, Route, Search, Send, Sparkles } from "lucide-react";
import MarkdownMessage from "@/components/MarkdownMessage";
import { useAuth } from "@/context/AuthContext";
import { ShiningText } from "@/components/ui/shining-text";
import { getApiUrl } from "@/app/utils/api-url";
import SearchableSelect from "@/components/ui/searchable-select";

type SourceChunk = {
  text: string;
  source: string;
  file_path: string;
  branch?: string | null;
  commit_sha?: string | null;
  language?: string | null;
  function_name?: string | null;
  class_name?: string | null;
  section_title?: string | null;
  start_line?: number | null;
  end_line?: number | null;
  score?: number | null;
  source_type: string;
};

type RetrievalTraceStep = {
  step: number;
  kind: string;
  tool: string;
  input?: Record<string, unknown>;
  summary: string;
};

type ChatMessage = {
  role: "assistant" | "user";
  content: string;
  sources?: SourceChunk[];
  trace?: RetrievalTraceStep[];
  retrievalMode?: string;
  fallbackUsed?: boolean;
};

type RepoOption = {
  repo: string;
  branch: string;
  commit_sha?: string | null;
};

const emptyAssistant: ChatMessage = {
  role: "assistant",
  content: "I am Cortex. Select a repository and ask me anything.",
  sources: [],
};

function shortSha(sha?: string | null) {
  return sha ? sha.slice(0, 7) : null;
}

function lineLabel(source: SourceChunk) {
  if (source.start_line && source.end_line) return `${source.start_line}-${source.end_line}`;
  if (source.start_line) return `${source.start_line}`;
  return null;
}

function sourceTitle(source: SourceChunk) {
  const lines = lineLabel(source);
  return lines ? `${source.file_path}:${lines}` : source.file_path;
}

function codeFence(source: SourceChunk) {
  const lang = source.language || "text";
  return `\`\`\`${lang}\n${source.text || ""}\n\`\`\``;
}

function traceLabel(step: RetrievalTraceStep) {
  return step.tool.replaceAll("_", " ");
}

function retrievalStatusLabel(msg: ChatMessage) {
  const mode = msg.retrievalMode || "ready";
  const labels: Record<string, string> = {
    hybrid: "hybrid",
    semantic: "semantic",
    graph: "graph",
    semantic_fallback: "semantic fallback",
  };
  const label = labels[mode] || mode.replaceAll("_", " ");
  const sourceText = msg.sources && msg.sources.length > 0 ? ` · ${msg.sources.length} cited chunks` : "";
  const fallbackText = msg.fallbackUsed && mode !== "hybrid" ? " · fallback" : "";
  return `${label}${sourceText}${fallbackText}`;
}

export default function QueryPage() {
  const API_URL = getApiUrl();
  const { authHeaders, user } = useAuth();
  const searchParams = useSearchParams();
  const [messages, setMessages] = useState<ChatMessage[]>([emptyAssistant]);
  const [input, setInput] = useState("");
  const [repoKey, setRepoKey] = useState("");
  const [allRepos, setAllRepos] = useState<RepoOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedSource, setSelectedSource] = useState<SourceChunk | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const autoRunDoneRef = useRef(false);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/repos`, { headers: authHeaders(), credentials: "include" })
      .then(res => res.json())
      .then(data => {
        const repoItems = (Array.isArray(data) ? data : []).map((r: any) => ({
          repo: r.repo,
          branch: r.branch || "main",
          commit_sha: r.commit_sha,
        }));
        if (!Array.isArray(data)) {
          console.warn("Unexpected repos response", data);
        }
        setAllRepos(repoItems);

        const requestedRepo = searchParams.get("repo");
        const requestedBranch = searchParams.get("branch") || "main";
        const requestedKey = requestedRepo === "all" ? "all" : `${requestedRepo}@${requestedBranch}`;
        const availableKeys = repoItems.map((r: RepoOption) => `${r.repo}@${r.branch}`);
        if (requestedRepo && (requestedRepo === "all" || availableKeys.includes(requestedKey))) {
          setRepoKey(requestedKey);
        } else if (repoItems.length > 0) {
          setRepoKey(`${repoItems[0].repo}@${repoItems[0].branch}`);
        } else {
          setRepoKey("all");
        }
      })
      .catch(e => console.error("Failed to load repos", e));
  }, [API_URL, authHeaders, searchParams]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const selectedRepo = allRepos.find((item) => `${item.repo}@${item.branch}` === repoKey);
  const repoOptions = React.useMemo(() => [
    { value: "all", label: "All repositories" },
    ...allRepos.map((repo) => ({
      value: `${repo.repo}@${repo.branch}`,
      label: repo.repo,
      meta: `${repo.branch}${repo.commit_sha ? ` · ${shortSha(repo.commit_sha)}` : ""}`,
    })),
  ], [allRepos]);

  const sendQuery = async (userMessage: string, repoOverride?: string) => {
    if (!userMessage.trim() || loading) return;

    setMessages(prev => [...prev, { role: "user", content: userMessage }]);
    setInput("");
    setLoading(true);

    try {
      const history = messages.slice(1).map(m => ({ role: m.role, content: m.content }));
      const activeKey = repoOverride ?? repoKey;
      const activeRepo = activeKey === "all" ? undefined : allRepos.find((item) => `${item.repo}@${item.branch}` === activeKey);

      const res = await fetch(`${API_URL}/api/v1/agent_query`, {
        method: "POST",
        credentials: "include",
        headers: authHeaders(),
        body: JSON.stringify({
          query: userMessage,
          repo: activeRepo?.repo,
          branch: activeRepo?.branch,
          history: history.length > 0 ? history : undefined
        })
      });

      if (!res.ok) {
        let detail = "API responded with error";
        try {
          const data = await res.json();
          detail = data?.detail || data?.message || detail;
        } catch {
          try {
            const text = await res.text();
            if (text) detail = text;
          } catch {
            // keep default detail
          }
        }
        throw new Error(`Request failed (${res.status}): ${detail}`);
      }
      const data = await res.json();
      const sources = data.sources || [];

      setMessages(prev => [...prev, {
        role: "assistant",
        content: data.answer,
        sources,
        trace: data.trace || [],
        retrievalMode: data.retrieval_mode,
        fallbackUsed: data.fallback_used,
      }]);
      if (sources.length > 0) {
        setSelectedSource(sources[0]);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      console.error(e);
      setMessages(prev => [...prev, { role: "assistant", content: `Warning: ${message}`, sources: [], trace: [] }]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (autoRunDoneRef.current) return;

    const shouldAutorun = searchParams.get("autorun") === "1";
    const q = (searchParams.get("q") || "").trim();
    const requestedRepo = searchParams.get("repo") || selectedRepo?.repo || "all";
    const requestedBranch = searchParams.get("branch") || selectedRepo?.branch || "main";
    const requestedKey = requestedRepo === "all" ? "all" : `${requestedRepo}@${requestedBranch}`;

    if (!shouldAutorun || !q) return;

    const availableKeys = allRepos.map((r) => `${r.repo}@${r.branch}`);
    const canUseRequestedRepo = requestedRepo === "all" || availableKeys.includes(requestedKey);
    if (!canUseRequestedRepo && allRepos.length > 0) {
      return;
    }

    if (requestedKey !== repoKey) {
      setRepoKey(requestedKey);
      return;
    }

    autoRunDoneRef.current = true;
    setInput(q);
    void sendQuery(q, requestedKey);
  }, [searchParams, repoKey, allRepos, selectedRepo]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    await sendQuery(input);
  };

  return (
    <section className="workspace query-workspace">
      <header className="query-header">
        <div>
          <h1>Intelligence</h1>
        </div>
        <div className="query-scope">
          <GitBranch size={16} />
          <SearchableSelect
            label="Repository"
            value={repoKey || "all"}
            options={repoOptions}
            placeholder="Select repository"
            emptyText="No indexed repositories found."
            onChange={setRepoKey}
          />
        </div>
      </header>

      <div className="query-shell">
        <div className="answer-pane">
          <div className="pane-title">
            <MessageSquare size={16} />
            <span>Answer</span>
          </div>

          <div className="query-message-list">
            {messages.map((msg, i) => (
              <article key={i} className={`query-message ${msg.role}`}>
                <div className="query-message-meta">
                  <span>{msg.role === "user" ? (user?.login || "You") : "Cortex"}</span>
                  {msg.role === "assistant" && (
                    <small>{retrievalStatusLabel(msg)}</small>
                  )}
                </div>
                <MarkdownMessage content={msg.content} />

                {msg.role === "assistant" && msg.trace && msg.trace.length > 0 && (
                  <details className="retrieval-trace">
                    <summary>
                      <Route size={14} />
                      <span>Retrieval trace</span>
                    </summary>
                    <div className="trace-steps">
                      {msg.trace.map((step) => (
                        <div className="trace-step" key={`${step.step}-${step.tool}`}>
                          <span className={`trace-kind ${step.kind}`}>{step.kind}</span>
                          <strong>{step.step}. {traceLabel(step)}</strong>
                          <p>{step.summary}</p>
                        </div>
                      ))}
                    </div>
                  </details>
                )}

                {msg.role === "assistant" && msg.sources && msg.sources.length > 0 && (
                  <div className="source-grid" aria-label="Cited sources">
                    {msg.sources.map((source, sourceIndex) => (
                      <button
                        type="button"
                        key={`${source.file_path}-${sourceIndex}`}
                        className={`source-card ${selectedSource === source ? "active" : ""}`}
                        onClick={() => setSelectedSource(source)}
                      >
                        <div className="source-card-title">
                          {source.source_type === "code" ? <Code2 size={14} /> : <FileText size={14} />}
                          <span>{sourceTitle(source)}</span>
                        </div>
                        <div className="source-card-meta">
                          <span>{source.language || source.source_type}</span>
                          {source.function_name && <span>{source.function_name}</span>}
                          {source.class_name && <span>{source.class_name}</span>}
                        </div>
                      </button>
                    ))}
                  </div>
                )}

                {msg.role === "assistant" && msg.sources && msg.sources.length === 0 && i > 0 && (
                  <p className="no-sources">No cited source was returned for this answer.</p>
                )}
              </article>
            ))}

            {loading && (
              <article className="query-message assistant loading">
                <div className="query-message-meta">
                  <span>Cortex</span>
                </div>
                <p className="loading-row">
                  <LoaderCircle className="spinner" size={16} /> <ShiningText text="Cortex is thinking..." />
                </p>
              </article>
            )}
            <div ref={endRef} />
          </div>

          <form className="query-composer" onSubmit={handleSubmit}>
            <Search size={16} />
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              aria-label="Message"
              placeholder="Ask about auth flow, ingestion, APIs, config, or architecture..."
              autoFocus
            />
            <button type="submit" disabled={loading || !input.trim()} aria-label="Send query">
              {loading ? <LoaderCircle className="spinner" size={16} /> : <Send size={16} />}
            </button>
          </form>
        </div>

        <aside className="evidence-pane">
          <div className="pane-title">
            <Sparkles size={16} />
            <span>Cited Chunk</span>
          </div>

          {!selectedSource ? (
            <div className="evidence-empty">Select a source to inspect the retrieved evidence.</div>
          ) : (
            <div className="evidence-content">
              <div className="evidence-path">{sourceTitle(selectedSource)}</div>
              <div className="evidence-meta-grid">
                <span>Branch</span>
                <strong>{selectedSource.branch || "main"}</strong>
                <span>Commit</span>
                <strong>{shortSha(selectedSource.commit_sha) || "unknown"}</strong>
                <span>Type</span>
                <strong>{selectedSource.source_type}</strong>
                <span>Language</span>
                <strong>{selectedSource.language || "text"}</strong>
                {selectedSource.function_name && (
                  <>
                    <span>Function</span>
                    <strong>{selectedSource.function_name}</strong>
                  </>
                )}
                {selectedSource.class_name && (
                  <>
                    <span>Class</span>
                    <strong>{selectedSource.class_name}</strong>
                  </>
                )}
                {selectedSource.section_title && (
                  <>
                    <span>Section</span>
                    <strong>{selectedSource.section_title}</strong>
                  </>
                )}
                {selectedSource.score != null && (
                  <>
                    <span>Score</span>
                    <strong>{selectedSource.score.toFixed(3)}</strong>
                  </>
                )}
              </div>
              <MarkdownMessage content={codeFence(selectedSource)} />
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}

