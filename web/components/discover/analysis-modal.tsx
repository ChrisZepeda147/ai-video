"use client";

import type { AnalysisItem } from "@/lib/types";

export function AnalysisModal({
  analysis,
  referenceTitle,
  onClose,
}: {
  analysis: AnalysisItem;
  referenceTitle: string;
  onClose: () => void;
}) {
  const inferred = analysis.inferred || {};
  const observed = analysis.observed || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="max-h-[90vh] w-full max-w-3xl overflow-y-auto rounded-xl border border-zinc-700 bg-zinc-950 p-6 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold text-zinc-100">Creative DNA</h2>
            <p className="mt-1 text-sm text-zinc-400">{referenceTitle}</p>
            {analysis.cached ? (
              <p className="mt-1 text-xs text-violet-400">Using existing analysis</p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-zinc-700 px-3 py-1 text-sm text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="mt-6 space-y-5 text-sm">
          {Object.keys(observed).length > 0 ? (
            <Section title="Observed">
              <KeyValue data={observed} />
            </Section>
          ) : null}

          {Object.keys(inferred).length > 0 ? (
            <Section title="Inferred">
              <KeyValue data={inferred} />
            </Section>
          ) : null}

          <Section title="Hook">
            <p className="text-zinc-300">{analysis.hook_type || "—"}</p>
          </Section>
          <Section title="Emotion">
            <p className="text-zinc-300">{analysis.emotional_trigger || "—"}</p>
          </Section>
          <Section title="Pacing">
            <p className="text-zinc-300">{analysis.pacing_style || "—"}</p>
          </Section>
          <Section title="Story structure">
            <p className="text-zinc-300">{analysis.story_structure || "—"}</p>
          </Section>
          <Section title="Visual mood">
            <p className="text-zinc-300">{analysis.visual_mood || "—"}</p>
          </Section>
          <Section title="Transferable patterns">
            <p className="text-zinc-300">{analysis.transferable_patterns || "—"}</p>
          </Section>
          <Section title="Avoid copying">
            <p className="text-zinc-300">{analysis.avoid_copying || "—"}</p>
          </Section>
        </div>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-zinc-500">{title}</h3>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function KeyValue({ data }: { data: Record<string, unknown> }) {
  return (
    <dl className="space-y-1">
      {Object.entries(data).map(([key, value]) => (
        <div key={key} className="grid grid-cols-[140px_1fr] gap-2">
          <dt className="text-zinc-500">{key.replace(/_/g, " ")}</dt>
          <dd className="text-zinc-300">
            {Array.isArray(value) ? value.join("; ") : String(value ?? "—")}
          </dd>
        </div>
      ))}
    </dl>
  );
}
