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
  calendarDateForWeekDay,
  type WeekDayId,
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
    const nextFocus = (prog?.focus_day as WeekDayId | undefined) ?? "mon";
    setFocusDay(nextFocus);

    setPlanSummary(
      res.data.plan
        ? `Week ${res.data.plan.status} · starts ${weekStart}`
        : "Copy ChatGPT prompt → paste reply → Save week (7am auto) or Run now.",
    );
  }, [weekStart, owner]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const ws = effectiveWeekStartForPaste(weekStart);
    const batchDay = calendarDateForWeekDay(ws, focusDay as WeekDayId);
    void fetchWeeklyHealth({ owner, day: batchDay }).then((h) => {
      if (h.ok) setHealth(h.data);
    });
  }, [weekStart, owner, focusDay]);

  const activeDay = focusDay;
  const batchDayIso = useMemo(
    () => calendarDateForWeekDay(effectiveWeekStartForPaste(weekStart), activeDay as WeekDayId),
    [weekStart, activeDay],
  );

  const anyRunning = useMemo(() => {
    const active = Object.values(slotMeta).some((m) =>
      ["running", "rerunning"].includes(m.status ?? ""),
    );
    return active || Boolean(health?.queue_busy) || (health?.running_command_jobs ?? 0) > 0;
  }, [slotMeta, health]);

  useEffect(() => {
    if (!anyRunning && !busy) return;
    const ms = busy ? 5000 : 15_000;
    const timer = setInterval(() => {
      void load();
      void fetchWeeklyHealth({ owner, day: batchDayIso }).then((h) => {
        if (h.ok) setHealth(h.data);
      });
    }, ms);
    return () => clearInterval(timer);
  }, [anyRunning, busy, load, owner, batchDayIso]);

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

  const dayProgress = useMemo(() => progress?.days.find((d) => d.day === activeDay), [progress, activeDay]);

  const dayMorning = useMemo(() => {
    if (!health || health.day !== batchDayIso) return health?.day_morning ?? null;
    return health.day_morning ?? null;
  }, [health, batchDayIso]);

  const dayOutcomeLabel = useMemo(() => {
    if (!dayMorning) return null;
    switch (dayMorning.outcome) {
      case "finished":
        return { text: "Yes — finished", className: "border-emerald-800/60 bg-emerald-950/40 text-emerald-200" };
      case "in_progress":
        return { text: "Rerunning / in progress", className: "border-amber-800/60 bg-amber-950/40 text-amber-200" };
      case "failed":
        return { text: "Failed — run again or retry slot", className: "border-red-800/60 bg-red-950/40 text-red-200" };
      case "not_finished":
        return {
          text: "No — 7am batch did not finish (still queued)",
          className: "border-red-800/60 bg-red-950/40 text-red-200",
        };
      case "pending":
        return { text: "Waiting for 7am", className: "border-zinc-700 bg-zinc-900/60 text-zinc-300" };
      default:
        return { text: "No plan for this day", className: "border-zinc-800 bg-zinc-900/40 text-zinc-500" };
    }
  }, [dayMorning]);

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
    const ws = effectiveWeekStartForPaste(weekStart);
    const target = runBatchTarget(ws);
    setBusy(true);
    setFocusDay(target.dayId);
    setSlotMeta((prev) => {
      const next = { ...prev };
      for (const n of SLOTS) {
        const key = `${target.dayId}-${n}` as SlotKey;
        const cur = next[key];
        if (cur?.status === "failed" || cur?.status === "queued") {
          next[key] = {
            ...cur,
            status: cur.status === "failed" ? "rerunning" : cur.status,
            error_message: null,
            job_key: null,
          };
        }
      }
      return next;
    });
    setStatus(
      "Rendering Monday videos (1→2→3) in the API — leave this tab open. Failed slots show Rerunning until this batch finishes.",
    );
    try {
      if (pasteText.trim()) {
        const ok = await saveWeekFromPaste();
        if (!ok) return;
      }
      const res = await postWeeklyRunDue({
        day: target.day,
        owner,
        retry_failed: true,
        limit: 3,
        serial: true,
        wait_complete: true,
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
        setStatus(`Deferred (${d.reason ?? "busy"}) — wait for current montage, then Run again.`);
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
          `Completed ${d.count} montage(s) for ${target.label}${keys.length ? ` · ${keys.join(", ")}` : ""}.`,
        );
      }
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function retrySlot(slotId: number) {
    setBusy(true);
    setSlotMeta((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(next) as SlotKey[]) {
        if (next[key]?.id === slotId) {
          next[key] = { ...next[key], status: "rerunning", error_message: null, job_key: null };
        }
      }
      return next;
    });
    try {
      const res = await postWeeklyRetrySlot(slotId);
      if (res.ok) await load();
      setStatus(res.ok ? "Marked rerunning — use Run now to render" : res.message);
    } finally {
      setBusy(false);
    }
  }

  function statusBadge(st?: string) {
    const s = st || "queued";
    const label = s === "rerunning" ? "rerunning" : s;
    const colors: Record<string, string> = {
      queued: "bg-zinc-800 text-zinc-300",
      rerunning: "bg-violet-900/60 text-violet-200",
      running: "bg-amber-900/60 text-amber-200",
      done: "bg-emerald-900/50 text-emerald-200",
      failed: "bg-red-900/50 text-red-200",
    };
    return (
      <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase ${colors[s] ?? colors.queued}`}>
        {label}
      </span>
    );
  }

  function displaySlotStatus(st?: string) {
    if (st === "rerunning") return "rerunning";
    if (st === "running") return "running";
    return st || "queued";
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
          {meta?.status === "failed" && meta.id && !busy ? (
            <button type="button" onClick={() => retrySlot(meta.id!)} className="text-xs text-violet-400">
              Retry
            </button>
          ) : null}
        </div>
        {meta?.status === "failed" && meta?.error_message ? (
          <p className="mt-1 text-xs text-red-400" title={meta.error_message}>
            {meta.error_message.length > 120 ? `${meta.error_message.slice(0, 120)}…` : meta.error_message}
          </p>
        ) : null}
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
            {busy ? `Rendering ${runTarget.label}…` : `Run ${runTarget.label} now (3 videos)`}
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
            {(health.reconcile?.stale?.stale_failed ?? 0) > 0 ? (
              <p className="text-amber-300">
                Cleared {health.reconcile?.stale?.stale_failed} stuck job(s) — use Run now or Retry on failed slots.
              </p>
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

        {dayOutcomeLabel ? (
          <div className={`mt-4 rounded-xl border p-4 ${dayOutcomeLabel.className}`}>
            <p className="text-sm font-semibold">
              {DAY_LABEL[activeDay as WeekDayId]} {batchDayIso} — {dayOutcomeLabel.text}
            </p>
            {dayMorning ? (
              <p className="mt-1 text-xs opacity-90">
                7am submitted: {dayMorning.morning_submitted ? "yes" : "no"}
                {dayMorning.catchup_ran ? " · catch-up ran on API start" : ""}
                {" · "}
                {dayMorning.stats.done}/3 done
                {dayMorning.stats.running ? ` · ${dayMorning.stats.running} running` : ""}
                {dayMorning.stats.queued ? ` · ${dayMorning.stats.queued} queued` : ""}
                {dayMorning.stats.rerunning ? ` · ${dayMorning.stats.rerunning} rerunning` : ""}
              </p>
            ) : null}
            <ul className="mt-3 space-y-2">
              {SLOTS.map((n) => {
                const key = `${activeDay}-${n}` as SlotKey;
                const st = displaySlotStatus(slotMeta[key]?.status);
                const sp = slots[key]?.speaker?.trim() || `Video ${n}`;
                const done = st === "done";
                return (
                  <li key={n} className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      readOnly
                      checked={done}
                      aria-label={`${DAY_LABEL_SHORT[activeDay]} video ${n} ${done ? "done" : st}`}
                      className="mt-0.5 h-4 w-4 rounded border-zinc-600"
                    />
                    <span>
                      {sp}{" "}
                      <span className="text-xs uppercase opacity-80">({st})</span>
                    </span>
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}

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
