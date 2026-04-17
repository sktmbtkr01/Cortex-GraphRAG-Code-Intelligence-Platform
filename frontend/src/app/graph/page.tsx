export default function GraphPage() {
  return (
    <section className="workspace">
      <header className="page-header">
        <p>Graph Explorer</p>
        <h1>Explore dependencies, calls, issues, and PR relationships.</h1>
      </header>
      <div className="graph-shell">
        <div className="graph-canvas">
          <span>Interactive graph canvas</span>
        </div>
        <aside className="detail-panel">
          <h2>Selection</h2>
          <p className="muted">
            Click a node to inspect metadata once Neo4j is connected.
          </p>
        </aside>
      </div>
    </section>
  );
}
