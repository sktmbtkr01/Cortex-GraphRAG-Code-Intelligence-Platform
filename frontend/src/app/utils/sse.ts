export type IngestStreamEvent = {
  type: "status" | "progress" | "done" | "error";
  state: "queued" | "running" | "done" | "error" | "lost";
  stage: string;
  message: string;
  meta?: Record<string, unknown>;
  repo?: string;
  stats?: Record<string, unknown> & {
    timings_ms?: Record<string, number>;
  };
  snapshot?: string;
};

export function openIngestEventStream(
  apiBaseUrl: string,
  jobId: string,
  onEvent: (event: IngestStreamEvent) => void,
  onError: () => void,
): EventSource {
  const streamUrl = `${apiBaseUrl}/api/v1/ingest/stream?job_id=${encodeURIComponent(jobId)}`;
  const es = new EventSource(streamUrl, { withCredentials: true });

  es.onmessage = (evt) => {
    try {
      const parsed = JSON.parse(evt.data) as IngestStreamEvent;
      onEvent(parsed);
    } catch {
      // ignore malformed chunk
    }
  };

  es.onerror = () => {
    onError();
  };

  return es;
}
