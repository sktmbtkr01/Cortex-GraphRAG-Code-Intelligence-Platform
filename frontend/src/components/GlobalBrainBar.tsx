"use client";

import React, { useEffect, useState } from "react";
import { Brain, Boxes, Network, GitBranch } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { getApiUrl } from "@/app/utils/api-url";

type GlobalStats = {
  chunks: number;
  nodes: number;
  repos: number;
  relationships: number;
};

const EMPTY_STATS: GlobalStats = {
  chunks: 0,
  nodes: 0,
  repos: 0,
  relationships: 0,
};

export default function GlobalBrainBar() {
  const { authHeaders } = useAuth();
  const API_URL = getApiUrl();
  const [stats, setStats] = useState<GlobalStats>(EMPTY_STATS);

  useEffect(() => {
    const fetchStats = async () => {
      try {
        const res = await fetch(`${API_URL}/api/v1/stats/global`, {
          headers: authHeaders(),
          credentials: "include",
        });
        if (!res.ok) return;
        const data = await res.json();
        setStats({
          chunks: Number(data.chunks || 0),
          nodes: Number(data.nodes || 0),
          repos: Number(data.repos || 0),
          relationships: Number(data.relationships || 0),
        });
      } catch {
        setStats(EMPTY_STATS);
      }
    };

    void fetchStats();
  }, [API_URL, authHeaders]);

  return (
    <section className="global-brain-row glass" aria-label="Global Brain metrics">
      <div className="global-brain-title">
        <Brain size={15} /> Global Brain
      </div>
      <div className="global-brain-metrics">
        <div className="metric-pill">
          <Boxes size={14} />
          <span>Chunks</span>
          <strong>{stats.chunks.toLocaleString()}</strong>
        </div>
        <div className="metric-pill">
          <Network size={14} />
          <span>Nodes</span>
          <strong>{stats.nodes.toLocaleString()}</strong>
        </div>
        <div className="metric-pill">
          <GitBranch size={14} />
          <span>Repos</span>
          <strong>{stats.repos.toLocaleString()}</strong>
        </div>
        <div className="metric-pill">
          <Network size={14} />
          <span>Connections</span>
          <strong>{stats.relationships.toLocaleString()}</strong>
        </div>
      </div>
    </section>
  );
}
