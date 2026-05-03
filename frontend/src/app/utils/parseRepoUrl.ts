export function parseRepoUrl(input: string): string | null {
  const value = input.trim();
  if (!value) return null;

  const cleaned = value
    .replace(/^git@github\.com:/i, "https://github.com/")
    .replace(/\.git$/i, "")
    .trim();

  const directMatch = cleaned.match(/^([A-Za-z0-9_.-]+)\/([A-Za-z0-9_.-]+)$/);
  if (directMatch) {
    return `${directMatch[1]}/${directMatch[2]}`;
  }

  try {
    const url = new URL(cleaned.startsWith("http") ? cleaned : `https://${cleaned}`);
    if (!url.hostname.toLowerCase().includes("github.com")) return null;

    const parts = url.pathname.split("/").filter(Boolean);
    if (parts.length < 2) return null;

    return `${parts[0]}/${parts[1].replace(/\.git$/i, "")}`;
  } catch {
    return null;
  }
}
