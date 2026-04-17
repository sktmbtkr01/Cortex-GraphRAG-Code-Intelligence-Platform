export default function ReposPage() {
  return (
    <section className="workspace">
      <header className="page-header">
        <p>Repositories</p>
        <h1>Manage indexed GitHub repositories.</h1>
      </header>
      <div className="panel-grid">
        <article className="panel">
          <h2>Add Repository</h2>
          <div className="form-row">
            <input aria-label="Repository name" placeholder="owner/repo-name" />
            <button type="button">Add</button>
          </div>
          <p className="muted">
            Ingestion, progress polling, and webhook status arrive in later
            phases.
          </p>
        </article>
        <article className="panel">
          <h2>Indexed Repos</h2>
          <div className="empty-state">No repositories indexed yet.</div>
        </article>
      </div>
    </section>
  );
}
