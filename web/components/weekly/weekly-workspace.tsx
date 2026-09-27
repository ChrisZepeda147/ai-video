"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  fetchWeekly,
  fetchWeeklyChatgptPrompt,
  fetchWeeklyHealth,
  getApiBaseUrl,
  postWeeklyApplyPaste,
  postWeeklyRetrySlot,
  postWeeklyRunDue,
  postWeeklySlots,
} from "@/lib/api";
import type { WeeklyHealthResponse, WeeklyProgress, WeeklySlot } from "@/lib/types";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const SLOTS = [1, 2, 3] as const;
const DAY_LABEL: Record<string, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

type SlotKey = `${(typeof DAYS)[number]}-${(typeof SLOTS)[number]}`;

type SlotCell = {
  speaker: string;
  visual: string;
  images: string[];
  make: string;
  requireStills: boolean;
};

function mondayOf(input: string): string {
  const d = input ? new Date(`${input}T12:00:00`) : new Date();
  const wd = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - wd);
  return d.toISOString().slice(0, 10);
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function calendarDayId(): string {
  return DAYS[(new Date().getDay() + 6) % 7];
}

function emptyGrid(): Record<SlotKey, SlotCell> {
  return Object.fromEntries(
    DAYS.flatMap((d) =>
      SLOTS.map((s) => [`${d}-${s}`, { speaker: "", visual: "", images: [], make: "", requireStills: false }]),
    ),
  ) as Record<SlotKey, SlotCell>;
}

export function WeeklyWorkspace() {
  const searchParams = useSearchParams();
  const initialOwner = searchParams.get("owner") === "stephen" ? "stephen" : "chris";
  const [owner, setOwner] = useState<"chris" | "stephen">(initialOwner);
  const [weekStart, setWeekStart] = useState(() => mondayOf(todayIso()));
  const [slots, setSlots] = useState<Record<SlotKey, SlotCell>>(emptyGrid);
  const [progress, setProgress] = useState<WeeklyProgress | null>(null);
  const [focusDay, setFocusDay] = useState<string>("mon");
  const [pasteText, setPasteText] = useState("");
  const [status, setStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<WeeklyHealthResponse | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [slotMeta, setSlotMeta] = useState<
    Record<SlotKey, { id?: number; status?: string; job_key?: string | null; video_id?: number | null; error_message?: string | null }>
  >({});

  const load = useCallback(async () => {
    const res = await fetchWeekly(weekStart, owner);
    if (!res.ok) {
      setStatus(res.message);
      return;
    }
    const next = emptyGrid();
    const meta: typeof slotMeta = {};
    for (const s of res.data.slots as WeeklySlot[]) {
      const key = `${s.day}-${s.slot}` as SlotKey;
      meta[key] = { id: s.id, status: s.status, job_key: s.job_key, video_id: s.video_id, error_message: s.error_message };
      next[key] = {
        speaker: s.speaker,
        visual: s.visual_direction,
        images: s.image_paths ?? [],
        make: s.image_prompt ?? "",
        requireStills: Boolean(s.require_stills_first),
      };
    }
    setSlots(next);
    setSlotMeta(meta);
    const prog = res.data.progress ?? null;
    setProgress(prog);
    if (prog?.focus_day) setFocusDay(prog.focus_day);
    else if (!res.data.slots.length) setFocusDay(calendarDayId());

    const h = await fetchWeeklyHealth({ owner });
    if (h.ok) setHealth(h.data);
    setStatus(res.data.plan ? `Week ${res.data.plan.status}` : "Paste ChatGPT plan below, then Apply week.");
  }, [weekStart, owner]);

  useEffect(() => {
    load();
  }, [load]);

  const activeDay = focusDay;
  const dayProgress = useMemo(() => progress?.days.find((d) => d.day === activeDay), [progress, activeDay]);

  function buildPayload(forDay?: string) {
    const entries = (Object.entries(slots) as Array<[SlotKey, SlotCell]>).filter(([key]) =>
      forDay ? key.startsWith(`${forDay}-`) : true,
    );
    return entries.map(([key, v]) => {
      const [day, slot] = key.split("-");
      return {
        day,
        slot: Number(slot),
        speaker: v.speaker.trim(),
        visual_direction: v.visual.trim(),
        image_paths: v.images,
        image_prompt: v.make.trim(),
        require_stills_first: v.requireStills,
      };
    });
  }

  async function copyChatgptPrompt() {
    const res = await fetchWeeklyChatgptPrompt(weekStart, owner);
    if (!res.ok) {
      setStatus(res.message);
      return;
    }
    await navigator.clipboard.writeText(res.data.prompt);
    setStatus("ChatGPT prompt copied — paste in ChatGPT, then paste reply below.");
  }

  async function applyPaste() {
    if (!pasteText.trim()) {
      setStatus("Paste ChatGPT reply first");
      return;
    }
    setBusy(true);
    try {
      const res = await postWeeklyApplyPaste({ week_start: weekStart, owner, text: pasteText, replace_week: true });
      if (!res.ok) {
        setStatus(res.message);
        return;
      }
      const warn = [...(res.data.parse_warnings ?? []), ...(res.data.warnings ?? [])].filter(Boolean);
      setStatus(`Applied ${res.data.slots_saved} videos${warn.length ? ` · ${warn.join("; ")}` : ""}`);
      setPasteText("");
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function saveDay() {
    setBusy(true);
    try {
      const payload = buildPayload().filter((s) => s.speaker || s.visual_direction || s.image_prompt);
      const res = await postWeeklySlots({ week_start: weekStart, owner, slots: payload });
      setStatus(res.ok ? "Saved" : res.message);
      if (res.ok) await load();
    } finally {
      setBusy(false);
    }
  }

  async function runDue() {
    setBusy(true);
    try {
      const res = await postWeeklyRunDue({ day: todayIso(), owner, retry_failed: true, limit: 3, serial: false });
      setStatus(
        res.ok
          ? res.data.deferred
            ? "Deferred — jobs still running"
            : `Started ${res.data.count} video(s) for today`
          : res.message,
      );
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function retrySlot(slotId: number) {
    setBusy(true);
    try {
      const res = await postWeeklyRetrySlot(slotId);
      if (res.ok) await load();
      setStatus(res.ok ? "Re-queued" : res.message);
    } finally {
      setBusy(false);
    }
  }

  function statusBadge(st?: string) {
    const s = st || "queued";
    const colors: Record<string, string> = {
      queued: "bg-zinc-800 text-zinc-300",
      running: "bg-amber-900/60 text-amber-200",
      done: "bg-emerald-900/50 text-emerald-200",
      failed: "bg-red-900/50 text-red-200",
    };
    return (
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${colors[s] ?? colors.queued}`}>{s}</span>
    );
  }

  function renderSlot(n: number) {
    const key = `${activeDay}-${n}` as SlotKey;
    const v = slots[key];
    const meta = slotMeta[key];
    return (
      <div key={n} className="rounded-xl border border-zinc-800 bg-zinc-950/80 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium text-zinc-200">Video {n}</span>
          {statusBadge(meta?.status)}
          {meta?.video_id ? (
            <a href={`/library?video=${meta.video_id}`} className="text-xs text-emerald-400 hover:underline">
              Library #{meta.video_id}
            </a>
          ) : null}
          {meta?.job_key ? (
            <a href={`/command?job=${encodeURIComponent(meta.job_key)}`} className="text-xs text-sky-400 hover:underline">
              {meta.job_key}
            </a>
          ) : null}
          {meta?.status === "failed" && meta.id ? (
            <button type="button" onClick={() => retrySlot(meta.id!)} className="text-xs text-violet-400">
              Retry
            </button>
          ) : null}
        </div>
        {meta?.error_message ? <p className="mt-1 text-xs text-red-400">{meta.error_message}</p> : null}
        <input
          value={v.speaker}
          onChange={(e) => setSlots((p) => ({ ...p, [key]: { ...v, speaker: e.target.value } }))}
          placeholder="Speaker"
          className="mt-3 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm"
        />
        <input
          value={v.visual}
          onChange={(e) => setSlots((p) => ({ ...p, [key]: { ...v, visual: e.target.value } }))}
          placeholder="B-roll / visuals"
          className="mt-2 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm"
        />
        <textarea
          value={v.make}
          onChange={(e) => setSlots((p) => ({ ...p, [key]: { ...v, make: e.target.value } }))}
          placeholder="Images to make (optional)"
          rows={2}
          className="mt-2 w-full rounded-lg border border-zinc-800 bg-zinc-900 px-3 py-2 text-sm"
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div className="flex flex-wrap items-center gap-3">
        {(["chris", "stephen"] as const).map((o) => (
          <button
            key={o}
            type="button"
            onClick={() => setOwner(o)}
            className={`rounded-lg px-3 py-1.5 text-sm capitalize ${owner === o ? "bg-violet-600 text-white" : "border border-zinc-800 text-zinc-400"}`}
          >
            {o}
          </button>
        ))}
        <label className="text-sm text-zinc-400">
          Week of{" "}
          <input
            type="date"
            value={weekStart}
            onChange={(e) => setWeekStart(mondayOf(e.target.value))}
            className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1"
          />
        </label>
      </div>

      <section className="rounded-xl border border-violet-900/40 bg-violet-950/20 p-4">
        <h2 className="text-sm font-semibold text-violet-200">1. ChatGPT → paste week</h2>
        <p className="mt-1 text-xs text-zinc-400">
          Copy prompt (includes last week). Paste ChatGPT reply below. Site splits Mon–Sun, 3 videos/day.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={copyChatgptPrompt} className="rounded-lg bg-violet-600 px-3 py-2 text-sm text-white">
            Copy ChatGPT prompt
          </button>
          <button type="button" onClick={applyPaste} disabled={busy} className="rounded-lg border border-violet-600 px-3 py-2 text-sm text-violet-200 disabled:opacity-50">
            Apply pasted week
          </button>
        </div>
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder={`MONDAY\n1. David Goggins | ocean drone 60fps\n2. ...\n\nTUESDAY\n1. ...`}
          rows={8}
          className="mt-3 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200"
        />
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-zinc-200">2. This week</h2>
          <div className="flex gap-2">
            <button type="button" onClick={saveDay} disabled={busy} className="rounded-lg border border-zinc-700 px-3 py-1.5 text-xs text-zinc-300">
              Save edits
            </button>
            <button type="button" onClick={runDue} disabled={busy} className="rounded-lg bg-zinc-100 px-3 py-1.5 text-xs font-medium text-zinc-900">
              Run today (3 at 7am)
            </button>
          </div>
        </div>
        {health ? (
          <p className="mt-2 text-xs text-zinc-500">
            Today {health.today_stats.done}/3 done · Agent {health.preflight.ok ? "OK" : "blocked"}
          </p>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-1">
          {DAYS.map((d) => {
            const row = progress?.days.find((x) => x.day === d);
            const isFocus = d === activeDay;
            const complete = row?.complete;
            return (
              <button
                key={d}
                type="button"
                onClick={() => setFocusDay(d)}
                className={`rounded-lg px-3 py-2 text-xs font-medium capitalize ${
                  isFocus
                    ? "bg-violet-600 text-white"
                    : complete
                      ? "bg-emerald-900/40 text-emerald-200"
                      : "bg-zinc-800 text-zinc-400"
                }`}
              >
                {DAY_LABEL[d]}
                {row ? ` ${row.done}/${row.filled || "·"}` : ""}
              </button>
            );
          })}
        </div>

        <p className="mt-3 text-sm text-zinc-400">
          {(() => {
            if (progress?.week_complete) return "Week complete — paste a new week or pick next Monday.";
            const idx = DAYS.indexOf(activeDay as (typeof DAYS)[number]);
            const next = idx >= 0 && idx < DAYS.length - 1 ? DAY_LABEL[DAYS[idx + 1]] : null;
            if (progress?.focus_day === activeDay && next)
              return `Focus: ${DAY_LABEL[activeDay]} — when 3/3 done, move to ${next}.`;
            return `Viewing ${DAY_LABEL[activeDay]}${dayProgress ? ` (${dayProgress.done}/${dayProgress.filled} done)` : ""}`;
          })()}
        </p>

        <div className="mt-4 space-y-3">{SLOTS.map((n) => renderSlot(n))}</div>
      </section>

      {status ? <p className="text-sm text-zinc-500">{status}</p> : null}

      <button type="button" className="text-xs text-zinc-500 underline" onClick={() => setShowAdvanced((v) => !v)}>
        {showAdvanced ? "Hide" : "Show"} advanced / 7am log
      </button>
      {showAdvanced && health?.log_tail ? (
        <pre className="max-h-40 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-500">{health.log_tail}</pre>
      ) : null}
    </div>
  );
}
