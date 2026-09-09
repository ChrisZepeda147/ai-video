import Image from "next/image";
import { ExternalLink } from "lucide-react";
import type { ReferenceItem } from "@/lib/types";
import { formatReferenceViews } from "@/lib/dashboard-stats";

function ViralityBadge({ score }: { score: number | null | undefined }) {
  if (score == null) {
    return (
      <span className="inline-flex rounded-md bg-zinc-700/40 px-2 py-0.5 text-xs text-zinc-400">
        —
      </span>
    );
  }
  const tone =
    score >= 90
      ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30"
      : score >= 80
        ? "bg-violet-500/15 text-violet-300 ring-violet-500/30"
        : score >= 70
          ? "bg-sky-500/15 text-sky-300 ring-sky-500/30"
          : "bg-zinc-500/15 text-zinc-300 ring-zinc-500/30";

  return (
    <span
      className={`inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${tone}`}
    >
      {Math.round(score)}
    </span>
  );
}

export function ReferenceList({ items }: { items: ReferenceItem[] }) {
  if (items.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-zinc-800 bg-zinc-900/30 px-6 py-12 text-center">
        <p className="text-sm font-medium text-zinc-300">No references found</p>
        <p className="mt-2 text-sm text-zinc-500">
          Try adjusting filters or run discovery ingest to populate the catalog.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {items.map((item) => (
        <article
          key={item.id}
          className="flex flex-col gap-4 rounded-xl border border-zinc-800 bg-zinc-900/40 p-4 lg:flex-row"
        >
          <div className="relative h-36 w-full shrink-0 overflow-hidden rounded-lg bg-zinc-800 lg:h-28 lg:w-48">
            {item.thumbnail_url ? (
              <Image
                src={item.thumbnail_url}
                alt=""
                fill
                className="object-cover"
                sizes="(max-width: 1024px) 100vw, 192px"
                unoptimized
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-zinc-500">
                No thumbnail
              </div>
            )}
          </div>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-md bg-orange-500/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-orange-300 ring-1 ring-orange-500/30">
                Reference only
              </span>
              {item.has_analysis ? (
                <span className="rounded-md bg-violet-500/15 px-2 py-0.5 text-[10px] font-medium text-violet-300 ring-1 ring-violet-500/30">
                  Creative DNA
                </span>
              ) : null}
              {item.exhausted ? (
                <span className="rounded-md bg-zinc-600/30 px-2 py-0.5 text-[10px] font-medium text-zinc-400 ring-1 ring-zinc-600/40">
                  Exhausted
                </span>
              ) : null}
            </div>

            <h3 className="mt-2 text-base font-semibold text-zinc-100">{item.title}</h3>
            <p className="mt-1 text-sm text-zinc-400">{item.channel ?? "Unknown channel"}</p>

            <div className="mt-3 flex flex-wrap gap-2">
              {item.niches.map((tag) => (
                <span
                  key={`${item.id}-${tag.niche}`}
                  className="rounded-md bg-zinc-800 px-2 py-0.5 text-xs capitalize text-zinc-300"
                >
                  {tag.niche}
                </span>
              ))}
            </div>

            <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-zinc-400">
              <span>{formatReferenceViews(item.view_count)} views</span>
              <span>{item.age_label ?? "—"} old</span>
              <ViralityBadge score={item.virality_score} />
              {item.internal_fit_score != null ? (
                <span
                  className="inline-flex items-center rounded-md bg-cyan-500/15 px-2 py-0.5 text-xs font-semibold text-cyan-300 ring-1 ring-cyan-500/30"
                  title={item.internal_fit_note ?? "Internal performance fit"}
                >
                  Fit {Math.round(item.internal_fit_score)}
                </span>
              ) : null}
              <span>{item.concepts_generated} concepts</span>
            </div>
          </div>

          <div className="flex shrink-0 items-start lg:items-center">
            <a
              href={item.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-2 rounded-lg border border-zinc-700 px-3 py-2 text-sm font-medium text-zinc-200 hover:bg-zinc-800"
            >
              Open YouTube
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
        </article>
      ))}
    </div>
  );
}
