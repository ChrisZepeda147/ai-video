"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  fetchAnalyticsOverview,
  fetchAnalyticsPatterns,
  fetchAnalyticsPosts,
  postAnalyticsRefresh,
} from "@/lib/api";
import type {
  AnalyticsOverview,
  AnalyticsPatternItem,
  AnalyticsPostItem,
} from "@/lib/types";

function TierBadge({ tier }: { tier?: string | null }) {
  if (!tier) return null;
  const tone =
    tier === "breakout"
      ? "bg-emerald-500/15 text-emerald-300"
      : tier === "strong"
        ? "bg-violet-500/15 text-violet-300"
        : tier === "underperforming"
          ? "bg-red-500/15 text-red-300"
          : "bg-zinc-500/15 text-zinc-300";
  return (
    <span className={`rounded px-2 py-0.5 text-xs capitalize ${tone}`}>{tier}</span>
  );
}

function PatternTable({ title, items }: { title: string; items: AnalyticsPatternItem[] }) {
  return (
    <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <h3 className="text-sm font-semibold text-zinc-200">{title}</h3>
      {items.length === 0 ? (
        <p className="mt-2 text-xs text-zinc-500">No data yet — publish Shorts and refresh analytics.</p>
      ) : (
        <ul className="mt-3 space-y-2">
          {items.slice(0, 8).map((item) => (
            <li key={item.label} className="flex items-center justify-between gap-2 text-xs">
              <span className="truncate text-zinc-300">{item.label}</span>
              <span className="shrink-0 text-zinc-500">
                score {item.avg_performance_score} · {item.post_count} posts
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function AnalyticsWorkspace() {
  const [overview, setOverview] = useState<AnalyticsOverview | null>(null);
  const [posts, setPosts] = useState<AnalyticsPostItem[]>([]);
  const [hooks, setHooks] = useState<AnalyticsPatternItem[]>([]);
  const [topics, setTopics] = useState<AnalyticsPatternItem[]>([]);
  const [formats, setFormats] = useState<AnalyticsPatternItem[]>([]);
  const [visuals, setVisuals] = useState<AnalyticsPatternItem[]>([]);
  const [niche, setNiche] = useState("");
  const [platform, setPlatform] = useState("");
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const params = {
      niche: niche || undefined,
      platform: platform || undefined,
    };
    const [ov, postRes, hookRes, topicRes, formatRes, visualRes] = await Promise.all([
      fetchAnalyticsOverview(params),
      fetchAnalyticsPosts({ ...params, limit: 20 }),
      fetchAnalyticsPatterns("hooks", params),
      fetchAnalyticsPatterns("topics", params),
      fetchAnalyticsPatterns("formats", params),
      fetchAnalyticsPatterns("visuals", params),
    ]);
    setLoading(false);
    if (ov.ok) setOverview(ov.data);
    if (postRes.ok) setPosts(postRes.data.items);
    if (hookRes.ok) setHooks(hookRes.data.items);
    if (topicRes.ok) setTopics(topicRes.data.items);
    if (formatRes.ok) setFormats(formatRes.data.items);
    if (visualRes.ok) setVisuals(visualRes.data.items);
  }, [niche, platform]);

  useEffect(() => {
    load();
  }, [load]);

  const onRefresh = async () => {
    setRefreshing(true);
    const result = await postAnalyticsRefresh({ force: true, limit: 50 });
    setRefreshing(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Refreshed ${result.data.refreshed} posts (${result.data.skipped} skipped, ${result.data.errors} errors)`);
    load();
  };

  const underperformers = posts.filter((p) => p.performance_tier === "underperforming");
  const breakouts = posts.filter((p) => p.performance_tier === "breakout");

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={niche}
          onChange={(e) => setNiche(e.target.value)}
          placeholder="Filter niche"
          className="rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-200"
        />
        <select
          value={platform}
          onChange={(e) => setPlatform(e.target.value)}
          className="rounded border border-zinc-700 bg-zinc-950 px-3 py-1.5 text-sm text-zinc-200"
        >
          <option value="">All platforms</option>
          <option value="youtube">YouTube</option>
          <option value="tiktok">TikTok</option>
          <option value="instagram">Instagram</option>
        </select>
        <button
          type="button"
          disabled={refreshing}
          onClick={onRefresh}
          className="rounded bg-violet-600 px-3 py-1.5 text-sm text-white disabled:opacity-50"
        >
          {refreshing ? "Refreshing…" : "Refresh analytics"}
        </button>
      </div>

      {message ? <p className="text-sm text-amber-300">{message}</p> : null}
      {loading ? <p className="text-sm text-zinc-500">Loading analytics…</p> : null}

      {overview && overview.total_published_posts < 5 ? (
        <div className="rounded-xl border border-amber-900/40 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
          LOW DATA CONFIDENCE — performance profiles and recommendations are advisory until more posts are published.
        </div>
      ) : null}

      {overview ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatCard label="Published posts" value={String(overview.total_published_posts)} />
          <StatCard label="Total views" value={overview.total_views.toLocaleString()} />
          <StatCard label="Views (7d)" value={overview.views_last_7_days.toLocaleString()} />
          <StatCard label="Avg score" value={overview.average_performance_score?.toFixed(1) ?? "—"} />
          <StatCard label="Views (30d)" value={overview.views_last_30_days.toLocaleString()} />
          <StatCard label="Breakouts" value={String(overview.breakout_count)} />
          <StatCard label="Underperformers" value={String(overview.underperforming_count)} />
          <StatCard label="With metrics" value={String(overview.posts_with_metrics)} />
        </div>
      ) : null}

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h3 className="text-sm font-semibold text-zinc-200">Top Performing Shorts</h3>
        {posts.length === 0 ? (
          <p className="mt-2 text-xs text-zinc-500">No published Shorts with analytics yet.</p>
        ) : (
          <div className="mt-3 space-y-3">
            {posts.slice(0, 10).map((post) => (
              <article key={post.publishing_job_id} className="flex flex-wrap items-center gap-3 rounded-lg border border-zinc-800/80 p-3">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-zinc-100">{post.title ?? `Job #${post.publishing_job_id}`}</p>
                  <p className="text-xs text-zinc-500">
                    {post.platform} · account #{post.account_id}
                    {post.niche ? ` · ${post.niche}` : ""}
                  </p>
                </div>
                <div className="text-right text-xs text-zinc-400">
                  <p>{(post.views ?? 0).toLocaleString()} views</p>
                  <p>score {post.performance_score?.toFixed(1) ?? "—"}</p>
                  <p>{post.velocity_views_per_day?.toFixed(0) ?? "—"} views/day</p>
                </div>
                <TierBadge tier={post.performance_tier} />
                <Link
                  href={`/videos?project=${post.production_project_id}`}
                  className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300"
                >
                  Details
                </Link>
              </article>
            ))}
          </div>
        )}
      </section>

      <div className="grid gap-4 lg:grid-cols-2">
        <PatternTable title="Winning Hooks" items={hooks} />
        <PatternTable title="Winning Topics" items={topics} />
        <PatternTable title="Winning Formats" items={formats} />
        <PatternTable title="Winning Visual Styles" items={visuals} />
      </div>

      {breakouts.length > 0 ? (
        <section className="rounded-xl border border-emerald-900/40 bg-emerald-950/20 p-4">
          <h3 className="text-sm font-semibold text-emerald-200">Breakout Shorts</h3>
          <ul className="mt-2 space-y-1 text-xs text-emerald-100/80">
            {breakouts.map((p) => (
              <li key={p.publishing_job_id}>
                {p.title} — {p.views?.toLocaleString()} views (score {p.performance_score})
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {underperformers.length > 0 ? (
        <section className="rounded-xl border border-red-900/40 bg-red-950/20 p-4">
          <h3 className="text-sm font-semibold text-red-200">Recent Underperformers</h3>
          <ul className="mt-2 space-y-1 text-xs text-red-100/80">
            {underperformers.slice(0, 5).map((p) => (
              <li key={p.publishing_job_id}>
                {p.title} — score {p.performance_score} (review creative ingredients on Videos page)
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-zinc-100">{value}</p>
    </div>
  );
}
