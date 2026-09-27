"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  fetchWeekly,
  fetchWeeklyChatgptPrompt,
  fetchWeeklyHealth,
  postWeeklyApplyPaste,
  postWeeklyParsePaste,
  postWeeklyRetrySlot,
  postWeeklyRunDue,
  postWeeklySlots,
} from "@/lib/api";
import type { WeeklyHealthResponse, WeeklyProgress, WeeklySlot } from "@/lib/types";
import {
  DAY_LABEL,
  WEEK_DAYS,
  calendarDayId,
  effectiveWeekStartForPaste,
  mondayOf,
  planningWeekStart,
  runBatchTarget,
  todayIso,
} from "@/lib/weekly-planning";

const SLOTS = [1, 2, 3] as const;

type SlotKey = `${(typeof WEEK_DAYS)[number]}-${(typeof SLOTS)[number]}`;

type SlotCell = {
  speaker: string;
  visual: string;
  images: string[];
  make: string;
  requireStills: boolean;
};

const DAY_LABEL_SHORT: Record<string, string> = {
  mon: "Mon",
  tue: "Tue",
  wed: "Wed",
  thu: "Thu",
  fri: "Fri",
  sat: "Sat",
  sun: "Sun",
};

function emptyGrid(): Record<SlotKey, SlotCell> {
  return Object.fromEntries(
    WEEK_DAYS.flatMap((d) =>
      SLOTS.map((s) => [`${d}-${s}`, { speaker: "", visual: "", images: [], make: "", requireStills: false }]),
    ),
  ) as Record<SlotKey, SlotCell>;
}

export function WeeklyWorkspace() {
  const searchParams = useSearchParams();
  const initialOwner = searchParams.get("owner") === "stephen" ? "stephen" : "chris";
  const [owner, setOwner] = useState<"chris" | "stephen">(initialOwner);
  const [weekStart, setWeekStart] = useState(() => planningWeekStart());
  const [slots, setSlots] = useState<Record<SlotKey, SlotCell>>(emptyGrid);
  const [progress, setProgress] = useState<WeeklyProgress | null>(null);
  const [focusDay, setFocusDay] = useState<string>("mon");
  const [pasteText, setPasteText] = useState("");
  const [parseHint, setParseHint] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [planSummary, setPlanSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [health, setHealth] = useState<WeeklyHealthResponse | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [slotMeta, setSlotMeta] = useState<
    Record<SlotKey, { id?: number; status?: string; job_key?: string | null; video_id?: number | null; error_message?: string | null }>
  >({});

  const runTarget = useMemo(() => runBatchTarget(weekStart), [weekStart]);
  const isSundayPlan = calendarDayId() === "sun";

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
    else setFocusDay("mon");

    const ws = effectiveWeekStartForPaste(weekStart);
    const batchDay = runBatchTarget(ws).day;
    const h = await fetchWeeklyHealth({ owner, day: batchDay });
    if (h.ok) setHealth(h.data);
    setPlanSummary(
      res.data.plan
        ? `Week ${res.data.plan.status} · starts ${weekStart}`
        : "Copy ChatGPT prompt → paste reply → Save week (7am auto) or Run now.",
    );
  }, [weekStart, owner]);

  useEffect(() => {
    load();
  }, [load]);

  const anyRunning = useMemo(() => {
    const slotRunning = Object.values(slotMeta).some((m) => m.status === "running");
    return slotRunning || Boolean(health?.queue_busy) || (health?.running_command_jobs ?? 0) > 0;
  }, [slotMeta, health]);

  useEffect(() => {
    if (!anyRunning) return;
    const timer = setInterval(() => {
      void load();
    }, 15_000);
    return () => clearInterval(timer);
  }, [anyRunning, load]);

  useEffect(() => {
    const t = pasteText.trim();
    if (t.length < 40) {
      setParseHint(null);
      return;
    }
    const timer = setTimeout(async () => {
      const res = await postWeeklyParsePaste(t);
      if (res.ok) {
        if (res.data.count === 0) {
          const w = res.data.warnings.filter(Boolean).slice(0, 2).join(" · ");
          setParseHint(w || "No videos parsed — need MONDAY headers and lines like: 1. Speaker | B-roll");
        } else {
          setParseHint(`Parsed ${res.data.count} videos${res.data.warnings.length ? " · check format" : ""}`);
        }
      }
    }, 500);
    return () => clearTimeout(timer);
  }, [pasteText]);

  const activeDay = focusDay;
  const dayProgress = useMemo(() => progress?.days.find((d) => d.day === activeDay), [progress, activeDay]);

  function buildPayload() {
    return (Object.entries(slots) as Array<[SlotKey, SlotCell]>).map(([key, v]) => {
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
    const ws = effectiveWeekStartForPaste(weekStart);
    if (ws !== weekStart) setWeekStart(ws);
    const res = await fetchWeeklyChatgptPrompt(ws, owner);
    if (!res.ok) {
      setStatus(res.message);
      return;
    }
    await navigator.clipboard.writeText(res.data.prompt);
    setStatus(
      isSundayPlan
        ? `Prompt copied for week starting ${ws} (Monday). Paste ChatGPT reply, then Save or Run Monday.`
        : "Prompt copied — paste ChatGPT reply below, then Save week or Run.",
    );
  }

  async function saveWeekFromPaste(): Promise<boolean> {
    if (!pasteText.trim()) {
      setStatus("Paste ChatGPT reply first");
      return false;
    }
    const ws = effectiveWeekStartForPaste(weekStart);
    if (ws !== weekStart) setWeekStart(ws);
    const res = await postWeeklyApplyPaste({ week_start: ws, owner, text: pasteText, replace_week: true });
    if (!res.ok) {
      setStatus(res.message);
      return false;
    }
    const warn = [...(res.data.parse_warnings ?? []), ...(res.data.warnings ?? [])].filter(Boolean);
    setStatus(
      `Saved ${res.data.slots_saved} videos for week ${ws} · Monday first${warn.length ? ` · ${warn.join("; ")}` : ""}`,
    );
    setPasteText("");
    setFocusDay("mon");
    await load();
    return true;
  }

  async function onSaveWeek() {
    setBusy(true);
    try {
      if (pasteText.trim()) {
        await saveWeekFromPaste();
        return;
      }
      const payload = buildPayload().filter((s) => s.speaker || s.visual_direction || s.image_prompt);
      const res = await postWeeklySlots({ week_start: weekStart, owner, slots: payload });
      setStatus(res.ok ? "Saved edits" : res.message);
      if (res.ok) await load();
    } finally {
      setBusy(false);
    }
  }

  async function onRunWeek() {
    setBusy(true);
    try {
      if (pasteText.trim()) {
        const ok = await saveWeekFromPaste();
        if (!ok) return;
      }
      const ws = effectiveWeekStartForPaste(weekStart);
      const target = runBatchTarget(ws);
      const res = await postWeeklyRunDue({
        day: target.day,
        owner,
        retry_failed: true,
        limit: 3,
        serial: false,
      });
      if (!res.ok) {
        setStatus(res.message);
        return;
      }
      setFocusDay(target.dayId);
      const d = res.data;
      if (d.error) {
        setStatus(`Could not start: ${d.error}`);
      } else if (d.deferred) {
        setStatus(`Deferred (${d.reason ?? "busy"}) — finish or wait on running Cursor jobs, then Run again.`);
      } else if ((d.count ?? 0) === 0) {
        const issues = d.preflight?.issues?.filter(Boolean).join(" · ");
        setStatus(
          issues
            ? `Nothing started — ${issues}`
            : `Nothing due for ${target.label} (${target.day}). Check week start matches saved plan.`,
        );
      } else {
        const keys = (d.submitted ?? []).map((s) => s.job_key).filter(Boolean);
        setStatus(
          `Started ${d.count} agent(s) for ${target.label} — status turns running below; open ${keys[0] ? "job link" : "Command"} to watch.`,
        );
      }
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
          Week starts{" "}
          <input
            type="date"
            value={weekStart}
            onChange={(e) => setWeekStart(mondayOf(e.target.value))}
            className="rounded-lg border border-zinc-800 bg-zinc-950 px-2 py-1"
          />
          <span className="ml-1 text-xs">(Monday)</span>
        </label>
      </div>

      <section className="rounded-xl border border-violet-900/40 bg-violet-950/20 p-4">
        <h2 className="text-sm font-semibold text-violet-200">Sunday feed → ChatGPT</h2>
        <p className="mt-1 text-xs text-zinc-400">
          {isSundayPlan
            ? `Planning for Monday ${weekStart}. Save splits Mon–Sun (3/day). 7am runs each day; Run now starts ${runTarget.label}.`
            : "Copy prompt, paste reply. Save for 7am auto-run or Run now for today's batch."}
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={copyChatgptPrompt} className="rounded-lg border border-violet-500 px-3 py-2 text-sm text-violet-100">
            Copy ChatGPT prompt
          </button>
          <button
            type="button"
            onClick={onSaveWeek}
            disabled={busy}
            className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            Save week
          </button>
          <button
            type="button"
            onClick={onRunWeek}
            disabled={busy}
            className="rounded-lg bg-zinc-100 px-4 py-2 text-sm font-medium text-zinc-900 disabled:opacity-50"
          >
            Run {runTarget.label} now (3 videos)
          </button>
        </div>
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          placeholder={`MONDAY\n1. David Goggins | ocean drone 60fps\n2. ...\n\nTUESDAY\n1. ...`}
          rows={10}
          className="mt-3 w-full rounded-lg border border-zinc-800 bg-zinc-950 px-3 py-2 font-mono text-xs text-zinc-200"
        />
        {parseHint ? <p className="mt-1 text-xs text-zinc-500">{parseHint}</p> : null}
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h2 className="text-sm font-semibold text-zinc-200">This week · one day at a time</h2>
        {health ? (
          <div className="mt-2 space-y-1 text-xs">
            <p className="text-zinc-500">
              {runTarget.label} batch {health.today_stats.done}/3 done ·{" "}
              {health.running_command_jobs > 0
                ? `${health.running_command_jobs} Cursor job(s) active`
                : health.preflight.ok
                  ? "Agent OK"
                  : "Agent blocked"}
              {anyRunning ? " · refreshing every 15s" : ""}
            </p>
            {!health.preflight.ok && health.preflight.issues.length ? (
              <p className="text-amber-300">{health.preflight.issues.join(" · ")}</p>
            ) : null}
          </div>
        ) : null}

        <div className="mt-4 flex flex-wrap gap-1">
          {WEEK_DAYS.map((d) => {
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
                {DAY_LABEL_SHORT[d]}
                {row ? ` ${row.done}/${row.filled || "·"}` : ""}
              </button>
            );
          })}
        </div>

        <p className="mt-3 text-sm text-zinc-400">
          {progress?.week_complete
            ? "Week complete — paste a new ChatGPT plan."
            : progress?.focus_day === activeDay
              ? `Focus ${DAY_LABEL_SHORT[activeDay]} — finish 3/3 then next day.`
              : `Viewing ${DAY_LABEL_SHORT[activeDay]}${dayProgress ? ` (${dayProgress.done}/${dayProgress.filled} done)` : ""}`}
        </p>

        <div className="mt-4 space-y-3">{SLOTS.map((n) => renderSlot(n))}</div>
      </section>

      {status ? <p className="text-sm text-violet-200">{status}</p> : null}
      {!status && planSummary ? <p className="text-sm text-zinc-500">{planSummary}</p> : null}

      <button type="button" className="text-xs text-zinc-500 underline" onClick={() => setShowAdvanced((v) => !v)}>
        {showAdvanced ? "Hide" : "Show"} 7am log
      </button>
      {showAdvanced && health?.log_tail ? (
        <pre className="max-h-40 overflow-auto rounded-lg border border-zinc-800 bg-zinc-950 p-3 text-xs text-zinc-500">{health.log_tail}</pre>
      ) : null}
    </div>
  );
}
