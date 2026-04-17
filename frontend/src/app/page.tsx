export default function Home() {
  return (
    <section className="workspace">
      <header className="page-header">
        <p>Chat</p>
        <h1>Ask Cortex about an indexed codebase.</h1>
      </header>
      <div className="chat-frame">
        <div className="toolbar">
          <select aria-label="Repository filter" defaultValue="all">
            <option value="all">All repositories</option>
          </select>
          <button type="button">Agent Query</button>
        </div>
        <div className="message-list">
          <div className="message assistant">
            <span>Cortex</span>
            <p>
              Phase 0 is live. Once ingestion lands, this panel will answer with
              cited files, functions, and line numbers.
            </p>
          </div>
        </div>
        <form className="composer">
          <input
            aria-label="Message"
            placeholder="Ask about auth flow, imports, recent changes..."
          />
          <button type="button">Send</button>
        </form>
      </div>
    </section>
  );
}
