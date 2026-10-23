// Small pure helpers for validating input and formatting values. No DOM access,
// so they can be unit tested with Node.

const OWNER = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$/;
const REPO = /^[A-Za-z0-9._-]{1,100}$/;

/**
 * Check a GitHub repository URL as the user types. Returns an error message, or
 * null if it looks valid. Mirrors the server's rules so the messages match.
 */
export function validateRepoUrl(raw) {
  let text = raw.trim();
  if (!text) return "Enter a GitHub repository URL";
  if (!text.includes("://")) text = `https://${text}`;

  let url;
  try {
    url = new URL(text);
  } catch {
    return "That's not a GitHub URL";
  }
  const host = url.hostname.toLowerCase().replace(/^www\./, "");
  if (!["http:", "https:"].includes(url.protocol) || host !== "github.com") {
    return "That's not a GitHub URL";
  }

  const [owner, repo] = url.pathname.split("/").filter(Boolean);
  if (!owner || !repo) return "Include the owner and repository name";
  const name = repo.replace(/\.git$/i, "");
  if (!OWNER.test(owner) || !REPO.test(name) || name === "." || name === "..") {
    return "That isn't a valid GitHub repository URL";
  }
  return null;
}

export const STATUS_LABELS = {
  fresh: "Fresh",
  ageing: "Ageing",
  stale: "Stale",
  unknown: "Unknown",
};

export const TRIAGE_LABELS = {
  open: "Open",
  acknowledged: "Acknowledged",
  fixed: "Fixed",
  ignored: "Ignored",
};

export const DEBT_LABELS = {
  low: "Low",
  moderate: "Moderate",
  high: "High",
};

export const FINDING_LABELS = {
  broken_refs: "Broken references",
  stale: "Stale",
  duplicated: "Duplicated rules",
  undocumented: "Not in README",
  oversized: "Oversized",
};

// Names and maximum points of the Prompt Debt Score components (see api/app/debt.py).
export const SCORE_PARTS = [
  ["conflicts", "Conflicting rules", 35],
  ["broken_refs", "Broken references", 25],
  ["drift", "Drift (staleness and churn)", 20],
  ["duplication", "Duplicated rules", 10],
  ["undocumented", "Not in README", 5],
  ["size", "Size", 5],
];

/** Split a finding key such as "stale:CLAUDE.md" into its type and path. */
export function parseFindingKey(key) {
  const index = key.indexOf(":");
  const type = key.slice(0, index);
  return { type, path: key.slice(index + 1), label: FINDING_LABELS[type] ?? type };
}

/** Commit counts are fetched one page at a time, so 100 means "100 or more". */
export function commitCount(count) {
  return count >= 100 ? "100+" : String(count);
}

export function shortSha(sha) {
  return sha.slice(0, 7);
}

export function formatDate(iso) {
  return new Date(iso).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function timeAgo(iso, now = Date.now()) {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return formatDate(iso);
}

/** Show only the start and end of a key, e.g. "AbCd…wXyZ". */
export function maskKey(key) {
  return key.length > 10 ? `${key.slice(0, 4)}…${key.slice(-4)}` : "••••";
}
