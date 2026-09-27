"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState, useTransition } from "react";
import { fetchWeeklyHealth } from "@/lib/api";
import type { WeeklyHealthResponse } from "@/lib/types";
import { PlatformBadge } from "@/components/platform-badge";
import type { CommandCenterOwnerBundle, CommandCenterResponse, PublishingOwner } from "@/lib/types";

const OWNER_TABS: Array<{ id: "all" | PublishingOwner; label: string }> = [
  { id: "all", label: "All" },
  { id: "chris", label: "Chris" },
  { id: "stephen", label: "Stephen" },
];

function ProgressPill({ label, done, target }: { label: string; done: number; target: number }) {
  const pct = target ? Math.min(100, Math.round((done / target) * 100)) : 0;
  return (
    <div className="min-w-[140px] flex-1">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="text-zinc-500">{label}</span>
        <span className="font-medium tabular-nums text-zinc-200">
          {done} / {target}
        </span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-zinc-800">
        <div className="h-full rounded-full bg-violet-500 transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function OwnerProgressCard({ bundle }: { bundle: CommandCenterOwnerBundle }) {
  const p = bundle.progress;
  return (
    <div className="rounded-xl border border-zinc-800/80 bg-zinc-900/40 p-4">
      <p className="text-xs font-semibold uppercase tracking-wider text-zinc-400">{bundle.owner}</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <ProgressPill label="Videos" done={p.videos.done} target={p.videos.target} />
        <ProgressPill label="TikTok" done={p.tiktok.done} target={p.tiktok.target} />
        <ProgressPill label="YouTube" done={p.youtube.done} target={p.youtube.target} />
        <div className="flex items-end">
          <div>
            <p className="text-xs text-zinc-500">Completion</p>
            <p className="text-2xl font-semibold tabular-nums text-zinc-100">{p.completion_pct}%</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500">{children}</h2>
  );
}

export function CommandCenterWorkspace({
  initial,
  initialOwner,
}: {
  initial: CommandCenterResponse;
  initialOwner: string;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [pending, startTransition] = useTransition();
  const [weeklyHealth, setWeeklyHealth] = useState<WeeklyHealthResponse | null>(null);
  const owner = (searchParams.get("owner") || initialOwner || "all").toLowerCase();
  const data = initial;

  useEffect(() => {
    const healthOwner = owner === "all" ? undefined : owner;
    fetchWeeklyHealth(healthOwner ? { owner: healthOwner } : {}).then((res) => {
      if (res.ok) setWeeklyHealth(res.data);
    });
  }, [owner]);

  const setOwner = useCallback(
    (next: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next === "all") params.delete("owner");
      else params.set("owner", next);
      startTransition(() => {
        router.push(`/?${params.toString()}`);
      });
    },
    [router, searchParams],
  );

  const activeOwners: CommandCenterOwnerBundle[] =
    owner === "all"
      ? (["chris", "stephen"] as const)
          .map((name) => data.owners[name])
          .filter(Boolean)
      : data.owners[owner]
        ? [data.owners[owner]]
        : [];

  const next = data.next_post;
  const combined = data.combined_progress;

  return (
    <div className={`space-y-10 ${pending ? "opacity-70" : ""}`}>
      <header className="space-y-4">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-violet-400/90">
            {data.brand}
          </p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-zinc-50">{data.date_label}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {OWNER_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setOwner(tab.id)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium capitalize transition ${
                owner === tab.id
                  ? "bg-violet-600 text-white"
                  : "border border-zinc-800 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </header>

      {next ? (
        <section className="rounded-2xl border border-violet-500/25 bg-gradient-to-br from-violet-950/50 to-zinc-950/80 p-6">
          <SectionTitle>Next post</SectionTitle>
          <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
            <div>
              <div className="flex items-center gap-2">
                <PlatformBadge platform={next.platform} />
                {next.owner && owner === "all" ? (
                  <span className="text-xs capitalize text-zinc-500">{next.owner}</span>
                ) : null}
              </div>
              <p className="mt-2 text-3xl font-semibold tabular-nums text-zinc-50">{next.time_label}</p>
              <p className="mt-1 text-sm text-violet-200/80">{next.away_label}</p>
              {next.production_project_id ? (
                <p className="mt-2 text-sm text-zinc-400">
                  Video: #{next.production_project_id}
                  {next.title ? ` · ${next.title}` : ""}
                </p>
              ) : next.title ? (
                <p className="mt-2 text-sm text-zinc-400">{next.title}</p>
              ) : null}
            </div>
            {next.production_project_id ? (
              <Link
                href={`/create?project_id=${next.production_project_id}`}
                className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500"
              >
                Open video
              </Link>
            ) : (
              <Link
                href="/videos"
                className="rounded-lg border border-zinc-700 px-4 py-2 text-sm text-zinc-200 hover:bg-zinc-900"
              >
                Pick video
              </Link>
            )}
          </div>
        </section>
      ) : null}

      <section className="flex flex-wrap gap-4 rounded-xl border border-zinc-800/80 bg-zinc-900/30 px-4 py-4">
        <ProgressPill label="Videos created" done={combined.videos.done} target={combined.videos.target} />
        <ProgressPill label="TikTok posts" done={combined.tiktok.done} target={combined.tiktok.target} />
        <ProgressPill label="YouTube Shorts" done={combined.youtube.done} target={combined.youtube.target} />
        <div className="min-w-[120px]">
          <p className="text-xs text-zinc-500">Daily completion</p>
          <p className="text-xl font-semibold tabular-nums text-zinc-100">{combined.completion_pct}%</p>
        </div>
        <div className="flex w-full flex-wrap gap-2">
          <Link href="/weekly" className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500">
            Weekly 7am plan
          </Link>
          {(owner === "all" ? ["chris", "stephen"] : [owner]).map((o) => (
            <Link key={o} href={`/weekly?owner=${o}`} className="rounded-lg border border-zinc-700 px-4 py-2 text-sm capitalize text-zinc-200 hover:bg-zinc-900">
              {o} week
            </Link>
          ))}
          {weeklyHealth ? (
            <p className="w-full text-xs text-zinc-500">
              7am queue: {weeklyHealth.due_count} due today · {weeklyHealth.today_stats.done}/3 done · Agent{" "}
              {weeklyHealth.preflight.ok ? "ready" : "blocked"} · {weeklyHealth.queue_busy ? "busy" : "idle"}
              {weeklyHealth.failed_digest?.length
                ? ` · ${weeklyHealth.failed_digest.length} failed slot(s) — see /weekly`
                : ""}
            </p>
          ) : null}
        </div>
      </section>

      {owner === "all" ? (
        <section className="grid gap-4 lg:grid-cols-2">
          {activeOwners.map((bundle) => (
            <OwnerProgressCard key={bundle.owner} bundle={bundle} />
          ))}
        </section>
      ) : null}

      <section className="space-y-3">
        <SectionTitle>Today&apos;s posting schedule</SectionTitle>
        <div className="divide-y divide-zinc-800/80 overflow-hidden rounded-xl border border-zinc-800/80">
          {activeOwners.flatMap((bundle) =>
            bundle.schedule.map((slot) => (
              <div
                key={`${bundle.owner}-${slot.window}-${slot.platform}-${slot.target_time}`}
                className="flex flex-wrap items-center justify-between gap-3 bg-zinc-900/20 px-4 py-3"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`h-2 w-2 rounded-full ${slot.completed ? "bg-emerald-400" : "bg-zinc-600"}`}
                  />
                  <div>
                    <p className="text-sm text-zinc-200">
                      <span className="capitalize text-zinc-500">{bundle.owner}</span>
                      {" · "}
                      {slot.window} · {slot.target_label}
                    </p>
                    <div className="mt-1 flex items-center gap-2">
                      <PlatformBadge platform={slot.platform} />
                      {slot.title ? (
                        <span className="truncate text-xs text-zinc-500">{slot.title}</span>
                      ) : (
                        <span className="text-xs text-zinc-600">{slot.completed ? "Posted" : "Open slot"}</span>
                      )}
                    </div>
                  </div>
                </div>
                {slot.platform_url ? (
                  <a
                    href={slot.platform_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-sky-400 hover:underline"
                  >
                    View post
                  </a>
                ) : slot.production_project_id ? (
                  <Link href={`/create?project_id=${slot.production_project_id}`} className="text-xs text-violet-300">
                    Open
                  </Link>
                ) : null}
              </div>
            )),
          )}
        </div>
      </section>

      <section className="space-y-3">
        <SectionTitle>Today&apos;s checklist</SectionTitle>
        <div className="grid gap-4 lg:grid-cols-2">
          {activeOwners.map((bundle) => (
            <div key={bundle.owner}>
              {owner === "all" ? (
                <p className="mb-2 text-xs font-semibold uppercase capitalize text-zinc-500">{bundle.owner}</p>
              ) : null}
              <ul className="grid gap-2">
                {bundle.checklist.map((item) => (
                  <li key={`${bundle.owner}-${item.id}`}>
                    <Link
                      href={item.href}
                      className={`flex items-center justify-between rounded-xl border px-4 py-3 text-sm transition ${
                        item.done
                          ? "border-emerald-500/20 bg-emerald-950/20 text-emerald-100"
                          : "border-zinc-800 bg-zinc-900/30 text-zinc-200 hover:border-zinc-700"
                      }`}
                    >
                      <span>{item.label}</span>
                      <span className="text-xs tabular-nums text-zinc-400">{item.detail}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-3">
        <SectionTitle>Views &amp; performance</SectionTitle>
        <div className="grid gap-4 md:grid-cols-2">
          {activeOwners.map((bundle) => (
            <div key={bundle.owner} className="rounded-xl border border-zinc-800/80 bg-zinc-900/30 p-4">
              <p className="text-xs font-semibold uppercase tracking-wider capitalize text-zinc-500">
                {bundle.owner}
              </p>
              <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
                <div>
                  <p className="text-xs text-zinc-500">Views (7d)</p>
                  <p className="font-semibold tabular-nums text-zinc-100">
                    {bundle.views.total_views_7d.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Views (30d)</p>
                  <p className="font-semibold tabular-nums text-zinc-100">
                    {bundle.views.total_views_30d.toLocaleString()}
                  </p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Linked posts</p>
                  <p className="font-semibold tabular-nums text-zinc-100">{bundle.views.linked_posts}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-500">Followers (live)</p>
                  <p className="font-semibold tabular-nums text-zinc-100">
                    {bundle.views.live_followers.toLocaleString()}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <SectionTitle>Videos ready / review</SectionTitle>
          {data.review_queue.length === 0 && data.ready_videos.length === 0 ? (
            <p className="text-sm text-zinc-600">No videos waiting — create on Make Short.</p>
          ) : null}
          {data.review_queue.length > 0 ? (
            <ul className="space-y-2">
              {data.review_queue.map((item) => (
                <li key={item.id}>
                  <Link
                    href={item.href}
                    className="block rounded-lg border border-amber-500/20 bg-amber-950/20 px-3 py-2 text-sm text-amber-100"
                  >
                    Review · {item.title}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
          {data.ready_videos.length > 0 ? (
            <ul className="mt-2 space-y-2">
              {data.ready_videos.slice(0, 5).map((v) => (
                <li key={v.key}>
                  <Link
                    href={v.href}
                    className="block rounded-lg border border-zinc-800 px-3 py-2 text-sm text-zinc-200 hover:bg-zinc-900"
                  >
                    Ready · {v.title}
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </div>

        <div className="space-y-3">
          <SectionTitle>7-day consistency</SectionTitle>
          {activeOwners.map((bundle) => (
            <div key={bundle.owner} className="rounded-xl border border-zinc-800/80 bg-zinc-900/30 p-4">
              <div className="mb-3 flex items-baseline justify-between">
                <span className="text-xs font-semibold uppercase capitalize text-zinc-500">{bundle.owner}</span>
                <span className="text-xs text-zinc-500">{bundle.streak_days} day streak</span>
              </div>
              <div className="flex gap-1">
                {bundle.week.map((day) => (
                  <div key={day.date_iso} className="flex-1 text-center">
                    <div
                      className={`mx-auto h-8 rounded-md ${
                        day.met_targets ? "bg-emerald-500/30" : day.completion_pct > 0 ? "bg-violet-500/20" : "bg-zinc-800"
                      }`}
                      title={`${day.completion_pct}%`}
                    />
                    <p className="mt-1 text-[10px] text-zinc-500">{day.date}</p>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      <details className="group rounded-xl border border-zinc-800/60 bg-zinc-950/40">
        <summary className="cursor-pointer list-none px-4 py-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-zinc-500 marker:content-none">
          Pipeline details
        </summary>
        <div className="border-t border-zinc-800/80 px-4 py-4">
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <p className="text-xs text-zinc-500">Viral references</p>
              <p className="text-lg font-semibold text-zinc-200">{data.pipeline.total_references}</p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">Concepts ready</p>
              <p className="text-lg font-semibold text-zinc-200">{data.pipeline.concepts_ready}</p>
            </div>
            <div>
              <p className="text-xs text-zinc-500">Visuals in review</p>
              <p className="text-lg font-semibold text-zinc-200">{data.pipeline.visuals_waiting_review}</p>
            </div>
          </div>
          <Link href="/discover" className="mt-4 inline-block text-xs text-violet-300 underline">
            Open discovery workspace
          </Link>
        </div>
      </details>
    </div>
  );
}
