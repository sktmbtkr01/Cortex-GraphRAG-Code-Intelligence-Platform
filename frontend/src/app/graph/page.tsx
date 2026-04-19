import { Metadata } from "next";
import GraphViewer from "@/components/GraphViewer";

export const metadata: Metadata = {
  title: "Graph - Cortex",
  description: "Interactive 3D Knowledge Graph explorer",
};

export default function GraphPage() {
  return (
    <div style={{ width: "100%", height: "100%" }}>
      <GraphViewer />
    </div>
  );
}
