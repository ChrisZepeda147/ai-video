/** Sunday feed → Monday-first week planning helpers. */

export const WEEK_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;

export type WeekDayId = (typeof WEEK_DAYS)[number];

export const DAY_LABEL: Record<WeekDayId, string> = {
  mon: "Monday",
  tue: "Tuesday",
  wed: "Wednesday",
  thu: "Thursday",
  fri: "Friday",
  sat: "Saturday",
  sun: "Sunday",
};

export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function mondayOf(input: string): string {
  const d = input ? new Date(`${input}T12:00:00`) : new Date();
  const wd = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - wd);
  return d.toISOString().slice(0, 10);
}

export function calendarDayId(): WeekDayId {
  return WEEK_DAYS[(new Date().getDay() + 6) % 7];
}

/** On Sunday, default to upcoming Monday; otherwise this week's Monday. */
export function planningWeekStart(from = todayIso()): string {
  const d = new Date(`${from}T12:00:00`);
  if (d.getDay() === 0) {
    d.setDate(d.getDate() + 1);
    return d.toISOString().slice(0, 10);
  }
  return mondayOf(from);
}

export function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T12:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

export function calendarDateForWeekDay(weekStartMon: string, day: WeekDayId): string {
  const idx = WEEK_DAYS.indexOf(day);
  return addDays(weekStartMon, idx >= 0 ? idx : 0);
}

export function dayIdForCalendarDate(weekStartMon: string, iso: string): WeekDayId {
  const start = new Date(`${weekStartMon}T12:00:00`).getTime();
  const target = new Date(`${iso}T12:00:00`).getTime();
  const diff = Math.round((target - start) / 86400000);
  if (diff < 0 || diff >= WEEK_DAYS.length) return "mon";
  return WEEK_DAYS[diff];
}

/** Which calendar day to run when user clicks Run (Sunday → Monday of selected week). */
/** Default tab when opening weekly: today if in this plan week, else Monday. */
export function defaultFocusDayId(weekStartMon: string): WeekDayId {
  return runBatchTarget(weekStartMon).dayId;
}

export function nextWeekDay(day: WeekDayId): WeekDayId | null {
  const idx = WEEK_DAYS.indexOf(day);
  if (idx < 0 || idx >= WEEK_DAYS.length - 1) return null;
  return WEEK_DAYS[idx + 1];
}

export function runBatchTarget(weekStartMon: string): { day: string; dayId: WeekDayId; label: string } {
  const today = todayIso();
  const weekEnd = addDays(weekStartMon, 6);
  if (today < weekStartMon || calendarDayId() === "sun") {
    return { day: weekStartMon, dayId: "mon", label: DAY_LABEL.mon };
  }
  if (today > weekEnd) {
    return { day: weekStartMon, dayId: "mon", label: DAY_LABEL.mon };
  }
  const dayId = calendarDayId();
  return {
    day: calendarDateForWeekDay(weekStartMon, dayId),
    dayId,
    label: DAY_LABEL[dayId],
  };
}

/** When saving a Sunday paste, snap week to upcoming Monday if needed. */
export function effectiveWeekStartForPaste(weekStart: string): string {
  const planned = planningWeekStart();
  if (calendarDayId() === "sun" && weekStart < planned) return planned;
  return weekStart;
}
