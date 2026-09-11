"use client";

import { useEffect, useState, type MouseEvent } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { fetchPublishingAccounts, postLinkVideoPost } from "@/lib/api";
import type { PublishingAccountItem, VideoLibraryItem } from "@/lib/types";

export function VideoLinkDialog({
  item,
  localOwner,
  onClose,
  onLinked,
}: {
  item: VideoLibraryItem;
  localOwner: string;
  onClose: () => void;
  onLinked: (message: string) => void;
}) {
  const [accounts, setAccounts] = useState<PublishingAccountItem[]>([]);
  const [accountId, setAccountId] = useState<number | "">("");
  const [platformUrl, setPlatformUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPublishingAccounts({ owner: localOwner }).then((result) => {
      if (!result.ok) return;
      const connected = result.data.items.filter(
        (a) => a.enabled && (a.auth_status === "connected" || a.auth_status === "verified"),
      );
      setAccounts(connected);
      if (connected.length === 1) setAccountId(connected[0].id);
    });
  }, [localOwner]);

  async function handleSubmit(e: MouseEvent) {
    e.stopPropagation();
    if (busy || !accountId || !platformUrl.trim()) return;
    setBusy(true);
    setError(null);
    const result = await postLinkVideoPost({
      account_id: Number(accountId),
      platform_url: platformUrl.trim(),
      slug: item.slug,
      title: item.speaker || item.title,
      project_id: item.project_id ?? undefined,
      output_path: item.output_path,
      niche: item.niche,
      source: item.source,
      origin_type: item.origin_type ?? item.source,
      format_profile: item.format_profile,
    });
    setBusy(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    const label = result.data.account_display_name || "account";
    onLinked(
      result.data.duplicate
        ? `Already linked to ${label}.`
        : `Linked to ${label} — analytics will refresh.`,
    );
    onClose();
  }

  return (
    <div
      className="mt-3 rounded-lg border border-sky-800/50 bg-sky-950/20 p-3"
      onClick={(e) => e.stopPropagation()}
    >
      <p className="text-xs font-medium uppercase tracking-wide text-sky-300">
        Link live post (analytics only)
      </p>
      <p className="mt-1 text-xs text-zinc-500">
        Paste the YouTube, TikTok, or Instagram URL after you upload manually. In-app upload comes later.
      </p>
      <label className="mt-2 block text-xs text-zinc-400">
        Account ({localOwner})
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : "")}
          className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
        >
          <option value="">Select account…</option>
          {accounts.map((account) => (
            <option key={account.id} value={account.id}>
              {account.display_name} ({account.platform})
            </option>
          ))}
        </select>
      </label>
      {accounts.length === 0 ? (
        <p className="mt-2 text-xs text-amber-300">
          No connected accounts for {localOwner}. Connect on{" "}
          <a href="/accounts" className="underline">
            Accounts
          </a>
          .
        </p>
      ) : null}
      <label className="mt-2 block text-xs text-zinc-400">
        Post URL
        <input
          value={platformUrl}
          onChange={(e) => setPlatformUrl(e.target.value)}
          placeholder="https://www.tiktok.com/@you/video/…"
          className="mt-1 w-full rounded-lg border border-zinc-700 bg-zinc-950 px-2 py-1.5 text-sm text-zinc-100"
        />
      </label>
      {accountId ? (
        <div className="mt-2">
          <PlatformBadge platform={accounts.find((a) => a.id === accountId)?.platform || "youtube"} />
        </div>
      ) : null}
      {error ? <p className="mt-2 text-xs text-red-400">{error}</p> : null}
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          disabled={busy || !accountId || !platformUrl.trim()}
          onClick={(e) => void handleSubmit(e)}
          className="rounded-lg bg-sky-600 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-40"
        >
          Link post
        </button>
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
