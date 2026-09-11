/** Human-readable duration, e.g. "1 minute 19 seconds". */
export function formatDuration(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds) || totalSeconds <= 0) {
    return "";
  }
  const seconds = Math.max(1, Math.round(totalSeconds));
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  const parts: string[] = [];
  if (minutes > 0) {
    parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  }
  if (rem > 0 || minutes === 0) {
    parts.push(`${rem} second${rem === 1 ? "" : "s"}`);
  }
  return parts.join(" ");
}

/** Repo-relative path for display (downloads/…). */
export function displayMediaPath(path: string | null | undefined): string | null {
  if (!path) return null;
  const normalized = path.replace(/\\/g, "/").replace(/^\/+/, "");
  for (const marker of ["downloads/", "shared_library/", "prompts/"]) {
    const idx = normalized.indexOf(marker);
    if (idx >= 0) return normalized.slice(idx);
  }
  return normalized;
}

export type VideoMediaKind = "audio" | "video" | "video_audio";

/** Videos tab category label. */
export function formatMediaKind(kind: string | null | undefined): string {
  if (kind === "video_audio") return "Video / Audio";
  if (kind === "audio") return "Audio";
  if (kind === "video") return "Video";
  return kind || "Video";
}

export function normalizeVideoMediaKind(kind: string | null | undefined): VideoMediaKind {
  if (kind === "audio") return "audio";
  if (kind === "video_audio") return "video_audio";
  return "video";
}

/** Compact clock, e.g. "1:07". */
export function formatTimecode(totalSeconds: number | null | undefined): string {
  if (totalSeconds == null || !Number.isFinite(totalSeconds) || totalSeconds < 0) {
    return "0:00";
  }
  const seconds = Math.round(totalSeconds);
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${minutes}:${rem.toString().padStart(2, "0")}`;
}
