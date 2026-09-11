"use client";

import type { ReactNode } from "react";
import { productionMediaUrl } from "@/lib/api";
import { displayMediaPath } from "@/lib/format";

export type MediaPreviewItem = {
  id?: number | string;
  label?: string | null;
  component_type?: string;
  local_path?: string | null;
  display_path?: string | null;
  preview_available?: boolean;
  media_kind?: "audio" | "video" | "other";
  url?: string | null;
  text_content?: string | null;
};

function inferKind(item: MediaPreviewItem): "audio" | "video" | "other" {
  if (item.media_kind === "audio" || item.component_type === "audio" || item.component_type === "caption") {
    return "audio";
  }
  if (
    item.media_kind === "video" ||
    item.component_type === "visual" ||
    item.component_type === "final"
  ) {
    return "video";
  }
  const path = (item.local_path || "").toLowerCase();
  if (path.endsWith(".mp3") || path.endsWith(".wav") || path.endsWith(".m4a")) return "audio";
  if (path.endsWith(".mp4") || path.endsWith(".mov") || path.endsWith(".webm")) return "video";
  return "other";
}

/** Path + inline preview + open link — reused on Library, Videos, Combinations. */
export function MediaPreviewCard({ item }: { item: MediaPreviewItem }) {
  const path = item.display_path || displayMediaPath(item.local_path);
  const mediaUrl =
    item.preview_available !== false && item.local_path ? productionMediaUrl(item.local_path) : null;
  const kind = inferKind(item);
  const title = item.label || item.component_type || "Media";

  return (
    <li className="rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2">
      <p className="text-sm text-zinc-200">{title}</p>
      {path ? <p className="mt-1 break-all font-mono text-[11px] text-violet-300/90">{path}</p> : null}
      {item.text_content ? (
        <p className="mt-1 line-clamp-3 text-xs text-zinc-500">{item.text_content}</p>
      ) : null}
      {item.url ? (
        <a href={item.url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-xs text-violet-300">
          {item.url}
        </a>
      ) : null}
      {mediaUrl && kind === "video" ? (
        <video src={mediaUrl} controls className="mt-2 aspect-[9/16] w-32 rounded-lg bg-black object-cover" />
      ) : null}
      {mediaUrl && kind === "audio" ? <audio src={mediaUrl} controls className="mt-2 w-full" /> : null}
      {mediaUrl ? (
        <a
          href={mediaUrl}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-block text-xs text-violet-300 hover:underline"
        >
          Open file
        </a>
      ) : item.local_path && item.preview_available === false ? (
        <p className="mt-2 text-xs text-amber-400/90">File missing on disk</p>
      ) : null}
    </li>
  );
}

export function CollapsibleMediaSection({
  title,
  count,
  defaultOpen = true,
  children,
}: {
  title: string;
  count: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  return (
    <details open={defaultOpen} className="rounded-2xl border border-zinc-800 bg-zinc-900/40 p-4">
      <summary className="cursor-pointer text-sm font-semibold text-zinc-100">
        {title} ({count})
      </summary>
      <div className="mt-3">{children}</div>
    </details>
  );
}
