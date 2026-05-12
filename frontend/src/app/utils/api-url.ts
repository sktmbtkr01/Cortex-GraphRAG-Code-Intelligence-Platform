export function getApiUrl() {
  const configured = process.env.NEXT_PUBLIC_API_URL;
  if (configured !== undefined) return configured.replace(/\/$/, "");
  return process.env.NODE_ENV === "development" ? "http://localhost:8000" : "";
}
