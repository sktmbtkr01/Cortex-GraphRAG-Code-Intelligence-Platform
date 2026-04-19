"use client";

import React, { useState, useEffect, useRef } from "react";
import MarkdownMessage from "@/components/MarkdownMessage";
import { useAuth } from "@/context/AuthContext";

export default function Home() {
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const { authHeaders, user } = useAuth();
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([
    { role: "assistant", content: "I am Cortex. Select a repository and ask me anything." }
  ]);
  const [input, setInput] = useState("");
  const [repo, setRepo] = useState("");
  const [allRepos, setAllRepos] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/repos`, { headers: authHeaders() })
      .then(res => res.json())
      .then(data => {
        setAllRepos(data.map((r: any) => r.repo));
        if (data.length > 0) setRepo(data[0].repo);
      })
      .catch(e => console.error("Failed to load repos", e));
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input;
    setMessages(prev => [...prev, { role: "user", content: userMessage }]);
    setInput("");
    setLoading(true);

    try {
      // Build history excluding the very first greeting
      const history = messages.slice(1).map(m => ({ role: m.role, content: m.content }));
      
      const res = await fetch(`${API_URL}/api/v1/agent_query`, {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({
          query: userMessage,
          repo: repo === "all" ? undefined : repo,
          history: history.length > 0 ? history : undefined
        })
      });
      
      if (!res.ok) throw new Error("API responded with error");
      const data = await res.json();
      
      setMessages(prev => [...prev, { role: "assistant", content: data.answer }]);
    } catch (e) {
      console.error(e);
      setMessages(prev => [...prev, { role: "assistant", content: "⚠️ Failed to reach Cortex Backend. Ensure it is running on port 8000." }]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="workspace" style={{ height: "100vh", display: "flex", flexDirection: "column" }}>
      <header className="page-header" style={{ flexShrink: 0 }}>
        <p>Chat</p>
        <h1>Code Intelligence Agent</h1>
      </header>
      
      <div className="chat-frame" style={{ flexGrow: 1, display: "flex", flexDirection: "column", overflow: "hidden", marginTop: 24, borderRadius: 8 }}>
        <div className="toolbar" style={{ flexShrink: 0 }}>
          <select value={repo} onChange={e => setRepo(e.target.value)} aria-label="Repository filter">
            <option value="all">All repositories</option>
            {allRepos.map(r => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        
        <div className="message-list" style={{ flexGrow: 1, overflowY: "auto", display: "flex", flexDirection: "column", gap: 16 }}>
          {messages.map((msg, i) => (
            <div key={i} className={`message ${msg.role}`} style={{ 
                alignSelf: msg.role === "user" ? "flex-end" : "flex-start",
                background: msg.role === "user" ? "var(--line)" : "var(--panel-strong)",
                borderColor: msg.role === "user" ? "transparent" : "var(--accent)"
            }}>
              <span>{msg.role === "user" ? (user?.login || "You") : "Cortex"}</span>
              <div style={{ marginTop: 8 }}>
                <MarkdownMessage content={msg.content} />
              </div>
            </div>
          ))}
          {loading && (
            <div className="message assistant" style={{ alignSelf: "flex-start", opacity: 0.7 }}>
              <span>Cortex</span>
              <p style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span className="spinner" /> Analyzing...
              </p>
            </div>
          )}
          <div ref={endRef} />
        </div>
        
        <form className="composer" onSubmit={handleSubmit} style={{ flexShrink: 0 }}>
          <input
            value={input}
            onChange={e => setInput(e.target.value)}
            aria-label="Message"
            placeholder="Ask about auth flow, imports, recent changes..."
            autoFocus
          />
          <button type="submit" disabled={loading || !input.trim()}>
            Send {loading ? "..." : "→"}
          </button>
        </form>
      </div>
    </section>
  );
}
