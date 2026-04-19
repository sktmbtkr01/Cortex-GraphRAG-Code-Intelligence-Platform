"use client";

import React, { useEffect, useState } from "react";
import { Trash2, RefreshCw, GitBranch, Lock, Globe, Camera, ShieldAlert, X } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import MarkdownMessage from "@/components/MarkdownMessage";

interface Repo {
  repo: string;
  is_private: boolean;
}

export default function ReposPage() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const { authHeaders } = useAuth();
  const [repos, setRepos] = useState<Repo[]>([]);
  const [newRepo, setNewRepo] = useState("");
  const [loading, setLoading] = useState(false);
  const [ingestStatus, setIngestStatus] = useState("");
  
  // Phase 8.5 state
  const [modalTitle, setModalTitle] = useState("");
  const [modalContent, setModalContent] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [modalLoading, setModalLoading] = useState(false);

  const fetchRepos = async () => {
    try {
      const res = await fetch(`${API_URL}/api/v1/repos`, { headers: authHeaders() });
      const data = await res.json();
      setRepos(data);
    } catch (e) {
      console.error("Failed to fetch repos", e);
    }
  };

  useEffect(() => {
    fetchRepos();
  }, []);

  const handleIngest = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRepo.includes("/")) {
      alert("Format must be owner/repo");
      return;
    }
    
    setLoading(true);
    setIngestStatus(`Ingesting ${newRepo}. This may take a few minutes...`);
    try {
      const res = await fetch(`${API_URL}/api/v1/ingest`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          repo: newRepo,
          branch: "main",
          include_issues: true,
          include_prs: true,
          include_commits: true
        })
      });
      const data = await res.json();
      if (!res.ok) alert("Error: " + data.detail);
      else {
        setIngestStatus(`Success: ${data.message}`);
        setNewRepo("");
        fetchRepos();
      }
    } catch (e) {
      setIngestStatus("Failed to ingest repository. Check backend logs.");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (repoName: string) => {
    if (!confirm(`Are you sure you want to delete ${repoName} from the index?`)) return;
    
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}`, {
        method: "DELETE",
        headers: authHeaders(),
      });
      if (res.ok) fetchRepos();
      else alert("Failed to delete repository.");
    } catch (e) {
      alert("Error reaching backend.");
    }
  };

  const handleViewSnapshot = async (repoName: string) => {
    setModalTitle(`Architecture Snapshot: ${repoName}`);
    setModalContent("");
    setIsModalOpen(true);
    setModalLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/snapshot`, { headers: authHeaders() });
      const data = await res.json();
      if (res.ok) setModalContent(data.snapshot);
      else setModalContent(`Error: ${data.detail}`);
    } catch (e) {
      setModalContent("Failed to connect to backend.");
    } finally {
      setModalLoading(false);
    }
  };

  const handleRunAudit = async (repoName: string) => {
    setModalTitle(`Security Audit: ${repoName}`);
    setModalContent("");
    setIsModalOpen(true);
    setModalLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/v1/repos/${repoName}/audit`, {
        method: "POST",
        headers: authHeaders()
      });
      const data = await res.json();
      if (res.ok) setModalContent(data.report);
      else setModalContent(`Error: ${data.detail}`);
    } catch (e) {
      setModalContent("Failed to run security audit.");
    } finally {
      setModalLoading(false);
    }
  };

  return (
    <section className="workspace">
      <header className="page-header">
        <p>Repositories</p>
        <h1>Manage indexed GitHub repositories.</h1>
      </header>
      
      <div className="panel-grid" style={{ marginTop: 24 }}>
        <article className="panel">
          <h2>Add Repository</h2>
          <form className="form-row" onSubmit={handleIngest} style={{ padding: 0, border: "none" }}>
            <input 
              value={newRepo}
              onChange={(e) => setNewRepo(e.target.value)}
              aria-label="Repository name" 
              placeholder="owner/repo-name" 
              disabled={loading}
            />
            <button type="submit" disabled={loading}>
              {loading ? <RefreshCw className="spinner" size={16} /> : "Add"}
            </button>
          </form>
          
          {ingestStatus && (
            <div style={{ marginTop: 16, padding: 12, background: "var(--panel-strong)", borderRadius: 6, fontSize: 14 }}>
              {ingestStatus}
            </div>
          )}
        </article>

        <article className="panel">
          <h2>Indexed Repos</h2>
          {repos.length === 0 ? (
            <div className="empty-state">No repositories indexed yet.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {repos.map(r => (
                <div key={r.repo} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: 16, border: "1px solid var(--line)", background: "var(--panel-strong)", borderRadius: 6 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <GitBranch size={20} color="var(--accent)" />
                    <div>
                      <strong style={{ display: "block", fontSize: 16 }}>{r.repo}</strong>
                      <span style={{ fontSize: 12, color: "var(--muted)", display: "flex", alignItems: "center", gap: 4 }}>
                        {r.is_private ? <><Lock size={12}/> Private</> : <><Globe size={12}/> Public</>}
                      </span>
                    </div>
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button 
                      onClick={() => handleViewSnapshot(r.repo)} 
                      style={{ background: "var(--panel)", border: "1px solid var(--line)", padding: "8px 12px", display: "flex", alignItems: "center", gap: 6 }}
                      title="Architecture Snapshot"
                    >
                      <Camera size={14} /> <span style={{ fontSize: 13 }}>Snapshot</span>
                    </button>
                    <button 
                      onClick={() => handleRunAudit(r.repo)} 
                      style={{ background: "rgba(243, 179, 95, 0.1)", border: "1px solid var(--warn)", color: "var(--warn)", padding: "8px 12px", display: "flex", alignItems: "center", gap: 6 }}
                      title="Run Security Audit"
                    >
                      <ShieldAlert size={14} /> <span style={{ fontSize: 13 }}>Audit</span>
                    </button>
                    <button 
                      onClick={() => handleDelete(r.repo)} 
                      style={{ background: "transparent", border: "1px solid var(--line)", color: "var(--warn)", padding: "8px 12px", marginLeft: 8 }}
                      title="Delete Repo"
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </article>
      </div>

      {isModalOpen && (
        <div style={{ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: "rgba(0,0,0,0.8)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 1000 }}>
          <div style={{ background: "var(--panel-strong)", border: "1px solid var(--line)", borderRadius: 8, width: "100%", maxWidth: 800, maxHeight: "90vh", display: "flex", flexDirection: "column" }}>
            <div style={{ padding: "16px 24px", borderBottom: "1px solid var(--line)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h2 style={{ fontSize: 18, margin: 0 }}>{modalTitle}</h2>
              <button 
                onClick={() => setIsModalOpen(false)}
                style={{ background: "transparent", border: "none", color: "var(--muted)", padding: 4 }}
              >
                <X size={20} />
              </button>
            </div>
            <div style={{ padding: 24, overflowY: "auto", flexGrow: 1 }}>
              {modalLoading ? (
                <div style={{ display: "flex", alignItems: "center", gap: 12, color: "var(--muted)" }}>
                  <RefreshCw className="spinner" size={20} /> Processing...
                </div>
              ) : (
                <div style={{ lineHeight: 1.6 }}>
                  <MarkdownMessage content={modalContent} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
