"use client";

import { useEffect, useState } from "react";
import { RiskBadge, riskLevel } from "@/components/shared/risk-badge";
import {
  fetchPublishingAccounts,
  postCreatePublishingJobs,
  productionMediaUrl,
} from "@/lib/api";
import type { ProductionProjectItem, PublishingAccountItem } from "@/lib/types";

type Props = {
  project: ProductionProjectItem;
  onClose: () => void;
  onPublished: (message: string) => void;
};

export function PublishDialog({ project, onClose, onPublished }: Props) {
  const [accounts, setAccounts] = useState<PublishingAccountItem[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [title, setTitle] = useState(project.title);
  const [caption, setCaption] = useState(project.hook_text || "");
  const [hashtags, setHashtags] = useState("");
  const [scheduleDate, setScheduleDate] = useState("");
  const [scheduleTime, setScheduleTime] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    fetchPublishingAccounts().then((r) => {
      if (r.ok) {
        setAccounts(r.data.items.filter((a) => a.enabled && a.posting_available));
        const nicheMatches = r.data.items.filter((a) => a.niche && project.niche && a.niche === project.niche);
        if (nicheMatches.length) {
          setSelected(new Set(nicheMatches.map((a) => a.id)));
        }
      }
    });
  }, [project.niche]);

  function toggleAccount(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function submit(publishNow: boolean) {
    if (selected.size === 0 || busy) return;
    setBusy(true);
    let scheduled_at: string | undefined;
    if (!publishNow && scheduleDate && scheduleTime) {
      scheduled_at = new Date(`${scheduleDate}T${scheduleTime}:00`).toISOString();
    }
    const result = await postCreatePublishingJobs({
      production_project_id: project.id,
      account_ids: Array.from(selected),
      title,
      caption,
      hashtags,
      scheduled_at,
      publish_now: publishNow,
    });
    setBusy(false);
    if (!result.ok) {
      onPublished(result.message);
      return;
    }
    onPublished(
      publishNow
        ? `Publishing started for ${result.data.items.length} destination(s)`
        : `Scheduled ${result.data.items.length} post(s)`,
    );
    onClose();
  }

  const previewUrl = productionMediaUrl(project.output_path);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-950 p-4 shadow-xl">
        <div className="flex items-start justify-between gap-3">
          <h2 className="text-lg font-semibold text-zinc-100">Publish Short</h2>
          <button type="button" onClick={onClose} className="text-zinc-500 hover:text-zinc-300">✕</button>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-2">
          {previewUrl ? (
            <video src={previewUrl} controls className="aspect-[9/16] w-full max-w-[200px] rounded-lg bg-black" />
          ) : null}
          <div className="space-y-2 text-xs text-zinc-400">
            <p className="font-medium text-zinc-200">{project.title}</p>
            <div className="flex flex-wrap gap-2">
              {project.reuse_confidence != null ? (
                <RiskBadge label="Reuse" score={project.reuse_confidence} level={riskLevel(project.reuse_confidence, true)} />
              ) : null}
              {project.rights_confidence != null ? (
                <RiskBadge label="Rights" score={project.rights_confidence} level={riskLevel(project.rights_confidence)} />
              ) : null}
              {project.monetization_confidence != null ? (
                <RiskBadge label="Monetization" score={project.monetization_confidence} level={riskLevel(project.monetization_confidence)} />
              ) : null}
            </div>
            <p className="text-zinc-600">Advisory scores only — low scores do not block publishing.</p>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          <label className="block text-xs text-zinc-400">
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100" />
          </label>
          <label className="block text-xs text-zinc-400">
            Caption
            <textarea value={caption} onChange={(e) => setCaption(e.target.value)} rows={3} className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100" />
          </label>
          <label className="block text-xs text-zinc-400">
            Hashtags
            <input value={hashtags} onChange={(e) => setHashtags(e.target.value)} placeholder="#luxury #mindset" className="mt-1 block w-full rounded border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100" />
          </label>
        </div>

        <div className="mt-4">
          <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">Destinations</p>
          {accounts.length === 0 ? (
            <p className="mt-2 text-sm text-zinc-600">Connect accounts on the Accounts page first.</p>
          ) : (
            <ul className="mt-2 space-y-2">
              {accounts.map((a) => (
                <li key={a.id} className="flex items-center gap-2 rounded border border-zinc-800 px-3 py-2 text-sm">
                  <input type="checkbox" checked={selected.has(a.id)} onChange={() => toggleAccount(a.id)} />
                  <span className="capitalize text-zinc-300">{a.platform}</span>
                  <span className="text-zinc-100">{a.display_name}</span>
                  {a.audit_note ? <span className="text-xs text-amber-500">({a.audit_note.slice(0, 40)}…)</span> : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <input type="date" value={scheduleDate} onChange={(e) => setScheduleDate(e.target.value)} className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm" />
          <input type="time" value={scheduleTime} onChange={(e) => setScheduleTime(e.target.value)} className="rounded border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm" />
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" disabled={busy || selected.size === 0} onClick={() => submit(true)} className="rounded bg-emerald-600 px-4 py-2 text-sm text-white disabled:opacity-50">
            Publish Now
          </button>
          <button type="button" disabled={busy || selected.size === 0 || !scheduleDate} onClick={() => submit(false)} className="rounded border border-zinc-700 px-4 py-2 text-sm disabled:opacity-50">
            Schedule
          </button>
          <button type="button" onClick={onClose} className="rounded border border-zinc-800 px-4 py-2 text-sm text-zinc-400">Cancel</button>
        </div>
      </div>
    </div>
  );
}
