"use client";

import React, { useRef, useEffect, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { Search } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

// Dynamically import ForceGraph3D to prevent SSR issues
const ForceGraph3D = dynamic(() => import("react-force-graph-3d"), { ssr: false });

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
  const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
  const { authHeaders } = useAuth();
  const [graphData, setGraphData] = useState<{ nodes: GraphNode[]; links: GraphLink[] }>({ nodes: [], links: [] });
  const [loading, setLoading] = useState(false);
  const [repo, setRepo] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [allRepos, setAllRepos] = useState<string[]>([]);
  const fgRef = useRef<any>(null);

  useEffect(() => {
    // Fetch repos for the dropdown
    fetch(`${API_URL}/api/v1/repos`, { headers: authHeaders() })
      .then((res) => res.json())
      .then((data) => {
        const repoNames = data.map((r: any) => r.repo);
        setAllRepos(repoNames);
        if (repoNames.length > 0) setRepo(repoNames[0]);
      })
      .catch((e) => console.error("Failed to fetch repos", e));
  }, []);

  const fetchGraphData = useCallback(async () => {
    setLoading(true);
    // Phase 8.4: Single-repo visual constraint — repo is required
    if (!repo || repo === "all") {
      setGraphData({ nodes: [], links: [] });
      setLoading(false);
      return;
    }
    let url = `${API_URL}/api/v1/graph/explore?repo=${encodeURIComponent(repo)}&depth=2`;
    if (searchTerm) url += `&center=${encodeURIComponent(searchTerm)}`;

    try {
      const res = await fetch(url, { headers: authHeaders() });
      const data = await res.json();
      
      // Post-process data for 3D visualization
      const processedNodes = data.nodes.map((n: GraphNode) => {
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

      setGraphData({ nodes: processedNodes, links: data.links });
    } catch (e) {
      console.error("Failed to fetch graph data", e);
    } finally {
      setLoading(false);
    }
  }, [repo, searchTerm]);

  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  const handleNodeClick = useCallback((node: any) => {
    setSelectedNode(node);
    if (fgRef.current) {
      // Aim at node from outside it
      const distance = 40;
      const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z);
      fgRef.current.cameraPosition(
        { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio },
        node, 
        3000
      );
    }
  }, []);

  return (
    <div className="graph-shell" style={{ position: "relative", width: "100%", height: "100%" }}>
      {/* Absolute Header Overlay */}
      <div style={{ position: "absolute", top: 16, left: 16, zIndex: 10, display: "flex", gap: 12 }}>
        <select value={repo} onChange={(e) => setRepo(e.target.value)} style={{ padding: "8px 12px", borderRadius: 4 }}>
          <option value="">Select a repository</option>
          {allRepos.map((r) => <option key={r} value={r}>{r}</option>)}
        </select>
        <div style={{ display: "flex", gap: 8, background: "#12150f", padding: "4px 8px", borderRadius: 4, border: "1px solid var(--line)", alignItems: "center" }}>
          <Search size={16} color="var(--muted)" />
          <input 
            type="text" 
            placeholder="Search center node..." 
            value={searchTerm} 
            onChange={(e) => setSearchTerm(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && fetchGraphData()}
            style={{ border: "none", background: "transparent", outline: "none" }}
          />
        </div>
      </div>
      
      {/* 3D Force Graph */}
      <div className="graph-canvas" style={{ flexGrow: 1, backgroundColor: "var(--background)" }}>
        {loading && <div style={{ position: "absolute", zIndex: 10, color: "var(--accent)" }}>Calculating Physics...</div>}
        <ForceGraph3D
          ref={fgRef}
          graphData={graphData}
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
          backgroundColor="#10120f"
        />
      </div>

      {/* Property Panel */}
      <aside className="detail-panel" style={{ width: 340, overflowY: "auto", background: "var(--panel)" }}>
        {selectedNode ? (
          <div>
            <h2 style={{ fontSize: 18, color: selectedNode.color || "var(--foreground)" }}>{selectedNode.type}</h2>
            <p style={{ color: "var(--muted)", margin: "8px 0 24px", wordBreak: "break-all" }}>{selectedNode.id}</p>
            
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {Object.entries(selectedNode.properties).map(([key, value]) => (
                <div key={key}>
                  <strong style={{ display: "block", fontSize: 12, textTransform: "uppercase", color: "var(--muted)" }}>{key}</strong>
                  <span style={{ fontSize: 14 }}>{String(value)}</span>
                </div>
              ))}
            </div>
            
            <button 
              style={{ marginTop: 24, width: "100%", padding: "8px" }}
              onClick={() => {
                setSearchTerm(selectedNode.name || selectedNode.id);
              }}
            >
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
