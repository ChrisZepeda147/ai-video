"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import {
  fetchAnalyticsBoard,
  fetchPublishingOwner,
  postAnalyticsRefresh,
} from "@/lib/api";
import type { AnalyticsAccountBoard, AnalyticsBoardResponse, PublishingOwner } from "@/lib/types";

const OWNERS: PublishingOwner[] = ["stephen", "chris"];
const PLATFORMS = ["youtube", "tiktok", "instagram", "facebook"] as const;

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-950/60 px-3 py-2">
      <p className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-sm font-semibold text-zinc-100">{value}</p>
    </div>
  );
}

function AccountPanel({ board }: { board: AnalyticsAccountBoard }) {
  const { account, overview, recent_posts, live_metrics } = board;
  const live = live_metrics && !live_metrics.error ? live_metrics : null;
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <PlatformBadge platform={account.platform} />
        <h3 className="text-sm font-semibold text-zinc-100">{account.display_name}</h3>
        {account.username ? <span className="text-xs text-zinc-500">@{account.username}</span> : null}
        <span className="rounded-full border border-zinc-700 px-2 py-0.5 text-[10px] uppercase text-zinc-500">
          {account.owner || "chris"}
        </span>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] uppercase ${
            account.auth_status === "connected"
              ? "bg-emerald-500/15 text-emerald-300"
              : "bg-zinc-800 text-zinc-400"
          }`}
        >
          {account.auth_status}
        </span>
      </div>

      {live ? (
        <div className="mb-3 grid gap-2 sm:grid-cols-3">
          {"follower_count" in live && live.follower_count != null ? (
            <Stat label="Followers" value={Number(live.follower_count).toLocaleString()} />
          ) : null}
          {"total_views" in live && live.total_views != null ? (
            <Stat label="Channel views" value={Number(live.total_views).toLocaleString()} />
          ) : null}
          {"video_count" in live && live.video_count != null ? (
            <Stat label="Videos" value={String(live.video_count)} />
          ) : null}
        </div>
      ) : null}

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Linked posts" value={String(overview.total_published_posts)} />
        <Stat label="Total views" value={overview.total_views.toLocaleString()} />
        <Stat label="Avg score" value={overview.average_performance_score?.toFixed(1) ?? "—"} />
        <Stat label="Breakouts" value={String(overview.breakout_count)} />
      </div>

      {recent_posts.length === 0 ? (
        <p className="mt-3 text-xs text-zinc-500">
          No linked posts yet — use <Link href="/videos" className="text-sky-300 underline">Videos → Link post</Link>.
        </p>
      ) : (
        <ul className="mt-3 space-y-2">
          {recent_posts.slice(0, 5).map((post) => (
            <li
              key={post.publishing_job_id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-zinc-800/80 px-3 py-2 text-xs"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium text-zinc-200">{post.title ?? `Job #${post.publishing_job_id}`}</p>
                {post.platform_url ? (
                  <a
                    href={post.platform_url}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate text-sky-400/90 hover:underline"
                  >
                    {post.platform_url}
                  </a>
                ) : null}
              </div>
              <div className="text-right text-zinc-400">
                <p>{(post.views ?? 0).toLocaleString()} views</p>
                <p>score {post.performance_score?.toFixed(1) ?? "—"}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AnalyticsWorkspace() {
  const [owner, setOwner] = useState<PublishingOwner>("chris");
  const [localOwner, setLocalOwner] = useState<PublishingOwner>("chris");
  const [board, setBoard] = useState<AnalyticsBoardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchPublishingOwner().then((result) => {
      if (result.ok && (result.data.owner === "stephen" || result.data.owner === "chris")) {
        setLocalOwner(result.data.owner);
        setOwner(result.data.owner);
      }
    });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchAnalyticsBoard({ owner, include_live: true });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setBoard(result.data);
  }, [owner]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onRefresh() {
    setRefreshing(true);
    const result = await postAnalyticsRefresh({ force: true, limit: 100 });
    setRefreshing(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(
      `Refreshed ${result.data.refreshed} posts (${result.data.skipped} skipped, ${result.data.errors} errors)`,
    );
    await load();
  }

  const byPlatform = (platform: string) =>
    (board?.accounts ?? []).filter((entry) => entry.account.platform === platform);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-zinc-800 p-1">
          {OWNERS.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setOwner(name)}
              className={`rounded-md px-3 py-1.5 text-sm capitalize ${
                owner === name ? "bg-violet-600 text-white" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
        <button
          type="button"
          disabled={refreshing}
          onClick={() => void onRefresh()}
          className="rounded bg-violet-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {refreshing ? "Refreshing…" : "Refresh analytics"}
        </button>
        {owner !== localOwner ? (
          <p className="text-xs text-zinc-500">
            Viewing {owner}&apos;s board — connect accounts on {owner}&apos;s machine for live OAuth.
          </p>
        ) : (
          <p className="text-xs text-zinc-500">
            This machine: <span className="capitalize text-zinc-300">{localOwner}</span> ·{" "}
            <Link href="/accounts" className="text-violet-300 underline">
              Accounts
            </Link>
          </p>
        )}
      </div>

      {message ? <p className="text-sm text-amber-300">{message}</p> : null}
      {loading ? <p className="text-sm text-zinc-500">Loading analytics…</p> : null}

      {!loading && board && board.account_count === 0 ? (
        <div className="rounded-xl border border-dashed border-zinc-800 p-8 text-center text-sm text-zinc-500">
          No accounts for {owner} yet.{" "}
          <Link href="/accounts" className="text-violet-300 underline">
            Connect YouTube, TikTok, and Instagram
          </Link>
          , then link posts from Videos.
        </div>
      ) : null}

      {PLATFORMS.map((platform) => {
        const panels = byPlatform(platform);
        if (panels.length === 0) return null;
        return (
          <div key={platform} className="space-y-3">
            <h2 className="text-sm font-semibold uppercase tracking-wide text-zinc-400">{platform}</h2>
            <div className="grid gap-4 lg:grid-cols-2">
              {panels.map((entry) => (
                <AccountPanel key={entry.account.id} board={entry} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
