"use client";

import React, { useRef, useEffect, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { Crosshair, Info, LoaderCircle, Search } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import SearchableSelect from "@/components/ui/searchable-select";
import { getApiUrl } from "@/app/utils/api-url";

// Dynamically import ForceGraph3D to prevent SSR issues
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

const NODE_LEGEND = [
  { type: "Repository", color: "#ffffff" },
  { type: "File", color: "#4a90e2" },
  { type: "Function", color: "#77c86b" },
  { type: "Class", color: "#b872ff" },
  { type: "Dependency", color: "#e2d14a" },
  { type: "Issue", color: "#f3b35f" },
  { type: "PullRequest", color: "#ff4a4a" },
  { type: "Contributor", color: "#4afff0" },
  { type: "Other", color: "#a9ad9e" },
];

interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties: Record<string, any>;
  val?: number;
  color?: string;
  name?: string;
}

interface GraphLink {
  source: string;
  target: string;
  type: string;
  properties: Record<string, any>;
}

export default function GraphViewer() {
  const API_URL = getApiUrl();
  const { authHeaders } = useAuth();
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [repoKey, setRepoKey] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [allRepos, setAllRepos] = useState<Array<{ repo: string; branch: string }>>([]);
  const fgRef = useRef<any>(null);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [canvasSize, setCanvasSize] = useState({ width: 1200, height: 720 });

  useEffect(() => {
    // Fetch repos for the dropdown
    fetch(`${API_URL}/api/v1/repos`, { headers: authHeaders(), credentials: "include" })
      .then((res) => {
        if (!res.ok) throw new Error(`Failed to load repos (${res.status})`);
        return res.json();
      })
      .then((data) => {
        const repoItems = Array.isArray(data)
          ? data.map((r: any) => ({ repo: r.repo, branch: r.branch || "main" })).filter((r: any) => r.repo)
          : [];
        setAllRepos(repoItems);
        if (repoItems.length > 0) setRepoKey(`${repoItems[0].repo}@${repoItems[0].branch}`);
      })
      .catch((e) => {
        const message = e instanceof Error ? e.message : "Failed to fetch repos";
        setError(message);
        console.error("Failed to fetch repos", e);
      });
  }, [API_URL, authHeaders]);

  const selectedRepo = useMemo(
    () => allRepos.find((item) => `${item.repo}@${item.branch}` === repoKey),
    [allRepos, repoKey],
  );

  const visibleLegend = useMemo(() => {
    const knownTypes = new Set(NODE_LEGEND.map((item) => item.type));
    const presentTypes = new Set(
      graphData.nodes.map((node) => (knownTypes.has(node.type) ? node.type : "Other")),
    );
    return NODE_LEGEND.filter((item) => presentTypes.has(item.type));
  }, [graphData.nodes]);

  const repoOptions = useMemo(
    () =>
      allRepos.map((repo) => ({
        value: `${repo.repo}@${repo.branch}`,
        label: repo.repo,
        meta: repo.branch,
      })),
    [allRepos],
  );

  const fetchGraphData = useCallback(async () => {
    setLoading(true);
    setError("");
    // Phase 8.4: Single-repo visual constraint — repo is required
    if (!selectedRepo) {
      setGraphData({ nodes: [], links: [] });
      setLoading(false);
      return;
    }
    let url = `${API_URL}/api/v1/graph/explore?repo=${encodeURIComponent(selectedRepo.repo)}&branch=${encodeURIComponent(selectedRepo.branch)}&depth=2`;
    if (searchTerm) url += `&center=${encodeURIComponent(searchTerm)}`;

    try {
      const res = await fetch(url, { headers: authHeaders(), credentials: "include" });
      if (!res.ok) {
        let detail = `Graph request failed (${res.status})`;
        try {
          const body = await res.json();
          detail = body?.detail || detail;
        } catch {
          // keep the status-based message
        }
        throw new Error(detail);
      }
      const data = await res.json();
      const rawNodes = Array.isArray(data.nodes) ? data.nodes : [];
      const rawLinks = Array.isArray(data.links) ? data.links : [];
      
      // Post-process data for 3D visualization
      const processedNodes = rawNodes.map((n: GraphNode) => {
        // Color mapping by type
        let color = "#a9ad9e"; // default muted
        let val = 3;
        
        switch (n.type) {
          case "File": color = "#4a90e2"; val = 5; break; // blue
          case "Function": color = "#77c86b"; val = 3; break; // green (accent)
          case "Class": color = "#b872ff"; val = 4; break; // purple
          case "Issue": color = "#f3b35f"; val = 4; break; // orange (warn)
          case "PullRequest": color = "#ff4a4a"; val = 4; break; // red
          case "Contributor": color = "#4afff0"; val = 6; break; // cyan
          case "Repository": color = "#ffffff"; val = 8; break; // white
          case "Dependency": color = "#e2d14a"; val = 4; break; // yellow
        }
        
        return {
          ...n,
          color,
          val,
          name: n.properties?.name || n.properties?.path || n.properties?.title || n.id
        };
      });

      setGraphData({ nodes: processedNodes, links: rawLinks });
    } catch (e) {
      const message = e instanceof Error ? e.message : "Failed to fetch graph data";
      setError(message);
      console.error("Failed to fetch graph data", e);
    } finally {
      setLoading(false);
    }
  }, [API_URL, authHeaders, selectedRepo, searchTerm]);

  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const updateSize = () => {
      const rect = canvas.getBoundingClientRect();
      setCanvasSize({
        width: Math.max(320, Math.floor(rect.width)),
        height: Math.max(360, Math.floor(rect.height)),
      });
    };

    updateSize();
    const observer = new ResizeObserver(updateSize);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!fgRef.current || graphData.nodes.length === 0) return;
    const timeout = window.setTimeout(() => {
      fgRef.current?.zoomToFit?.(700, 120);
    }, 450);
    return () => window.clearTimeout(timeout);
  }, [graphData.nodes.length, graphData.links.length, canvasSize.width, canvasSize.height]);

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
    if (fgRef.current) {
      // Aim at node from outside it
      const distance = 150;
      const nodeDistance = Math.max(1, Math.hypot(node.x, node.y, node.z));
      const distRatio = 1 + distance / nodeDistance;
      fgRef.current.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
        node, 
        1800
      );
    }
  }, []);

  return (
    <div className="graph-shell">
      <section className="graph-stage" aria-label="Knowledge graph explorer">
        <div className="graph-controls">
          <div className="graph-repo-select">
            <SearchableSelect
              label="Repository"
              value={repoKey}
              options={repoOptions}
              placeholder="Select a repository"
              emptyText="No indexed repositories"
              onChange={setRepoKey}
            />
          </div>
          <label className="graph-search">
          <Search size={17} />
          <input 
            type="text" 
            placeholder="Search center node..." 
            value={searchTerm} 
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchGraphData()}
          />
          </label>
        </div>

      <div
        className="graph-legend"
        aria-label="Graph legend"
      >
        <strong>Node Legend</strong>
        <div>
          {visibleLegend.map((item) => (
            <span key={item.type}>
              <span style={{ background: item.color }} />
              {item.type}
            </span>
          ))}
        </div>
      </div>
      
      {/* 3D Force Graph */}
      <div className="graph-canvas" ref={canvasRef}>
        {loading && (
          <div className="graph-status">
            <LoaderCircle size={16} className="spin" />
            Calculating physics...
          </div>
        )}
        {error && <div className="graph-error">{error}</div>}
        <ForceGraph3D
          ref={fgRef}
          graphData={graphData}
          width={canvasSize.width}
          height={canvasSize.height}
          nodeLabel="name"
          nodeColor="color"
          nodeVal="val"
          linkDirectionalArrowLength={3.5}
          linkDirectionalArrowRelPos={1}
          linkColor={(link: any) => {
            switch (link.type) {
              case "IMPORTS": return "#4a90e2";
              case "CALLS": return "#77c86b";
              case "INHERITS": return "#b872ff";
              case "MODIFIES": return "#ff4a4a";
              default: return "rgba(255,255,255,0.2)";
            }
          }}
          linkCurvature={0.2}
          onNodeClick={handleNodeClick}
          backgroundColor="#050806"
        />
      </div>
      </section>

      {/* Property Panel */}
      <aside className="detail-panel">
        {selectedNode ? (
          <div className="graph-node-details">
            <span className="graph-node-kicker">
              <Info size={15} />
              Selected Node
            </span>
            <h2 style={{ color: selectedNode.color || "var(--foreground)" }}>{selectedNode.type}</h2>
            <p>{selectedNode.id}</p>
            
            <div className="graph-property-list">
              {Object.entries(selectedNode.properties || {}).map(([key, value]) => (
                <div className="graph-property" key={key}>
                  <strong>{key}</strong>
                  <span>{String(value)}</span>
                </div>
              ))}
            </div>
            
            <button 
              className="graph-center-button"
              onClick={() => {
                setSearchTerm(selectedNode.name || selectedNode.id);
              }}
            >
              <Crosshair size={16} />
              Set as Center Node
            </button>
          </div>
        ) : (
          <div className="empty-state">
            Select a node to view properties
          </div>
        )}
      </aside>
    </div>
  );
}
