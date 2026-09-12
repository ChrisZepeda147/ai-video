"use client";

import { useEffect, useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { fetchPublishingOwner, postUpdateVideoPostingStatus } from "@/lib/api";
import type { OwnerPostingStatus, ProductionLibraryVideo, PublishingOwner, VideoPostingStatus } from "@/lib/types";

type PlatformKey = "tiktok" | "youtube";
type OwnerKey = PublishingOwner;

const PLATFORMS: PlatformKey[] = ["tiktok", "youtube"];
const OWNERS: OwnerKey[] = ["chris", "stephen"];

function platformButtonClass(active: boolean, linked: boolean) {
  if (linked && active) {
    return "border-sky-600/50 bg-sky-950/40 text-sky-100";
  }
  if (active) {
    return "border-emerald-600/50 bg-emerald-950/40 text-emerald-100";
  }
  return "border-zinc-700 bg-zinc-900/50 text-zinc-400 hover:border-zinc-600 hover:text-zinc-200";
}

function ownerSlot(status: VideoPostingStatus | undefined, owner: OwnerKey): OwnerPostingStatus {
  return (
    status?.by_owner?.[owner] ?? {
      posted: false,
      manual: {},
      linked: [],
      effective: {},
    }
  );
}

function OwnerPostingToggles({
  videoId,
  owner,
  slot,
  compact,
  busyKey,
  onToggle,
}: {
  videoId: number;
  owner: OwnerKey;
  slot: OwnerPostingStatus;
  compact?: boolean;
  busyKey: string | null;
  onToggle: (owner: OwnerKey, platform: PlatformKey) => void;
}) {
  const linkedPlatforms = new Set(slot.linked.map((link) => link.platform));

  return (
    <div className={compact ? "space-y-1" : "space-y-2"}>
      <p className={`font-semibold capitalize text-zinc-400 ${compact ? "text-[10px]" : "text-xs"}`}>{owner}</p>
      <div className="flex flex-wrap gap-2">
        {PLATFORMS.map((platform) => {
          const active = Boolean(slot.effective[platform]);
          const linked = linkedPlatforms.has(platform);
          const manualMark = Boolean(slot.manual[platform]);
          const toggleKey = `${owner}:${platform}`;
          return (
            <button
              key={`${owner}-${platform}`}
              type="button"
              disabled={busyKey !== null}
              onClick={() => onToggle(owner, platform)}
              title={
                linked
                  ? `${owner} linked via API — click to add or clear manual mark`
                  : active
                    ? `${owner} marked posted — click to unmark`
                    : `Mark ${owner} posted to ${platform}`
              }
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2 py-1 text-xs transition disabled:opacity-50 ${platformButtonClass(active, linked)}`}
            >
              <PlatformBadge platform={platform} />
              <span>{busyKey === toggleKey ? "…" : active ? "Used" : "Mark used"}</span>
              {linked && manualMark ? (
                <span className="text-[10px] opacity-70">API+manual</span>
              ) : linked ? (
                <span className="text-[10px] opacity-70">API</span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function PostingStatusEditor({
  videoId,
  status,
  compact = false,
  onUpdated,
}: {
  videoId: number;
  status?: VideoPostingStatus;
  compact?: boolean;
  onUpdated?: (video: ProductionLibraryVideo) => void;
}) {
  const [selectedOwner, setSelectedOwner] = useState<OwnerKey>("chris");
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchPublishingOwner().then((result) => {
      if (result.ok && (result.data.owner === "chris" || result.data.owner === "stephen")) {
        setSelectedOwner(result.data.owner);
      }
    });
  }, []);

  async function toggle(owner: OwnerKey, platform: PlatformKey) {
    if (busyKey) return;
    const slot = ownerSlot(status, owner);
    const toggleKey = `${owner}:${platform}`;
    setBusyKey(toggleKey);
    setError(null);
    const next = !slot.effective[platform];
    const result = await postUpdateVideoPostingStatus(videoId, { owner, [platform]: next });
    setBusyKey(null);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    onUpdated?.(result.data);
  }

  if (compact) {
    return (
      <div className="space-y-2" onClick={(e) => e.stopPropagation()}>
        <p className="text-[10px] font-medium uppercase tracking-wider text-zinc-500">Posted by</p>
        {OWNERS.map((owner) => (
          <OwnerPostingToggles
            key={owner}
            videoId={videoId}
            owner={owner}
            slot={ownerSlot(status, owner)}
            compact
            busyKey={busyKey}
            onToggle={toggle}
          />
        ))}
        {error ? <p className="text-xs text-red-300">{error}</p> : null}
      </div>
    );
  }

  return (
    <div className="space-y-3" onClick={(e) => e.stopPropagation()}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">Posted by owner</p>
        <div className="flex gap-1">
          {OWNERS.map((owner) => (
            <button
              key={owner}
              type="button"
              onClick={() => setSelectedOwner(owner)}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium capitalize transition ${
                selectedOwner === owner
                  ? "bg-violet-600 text-white"
                  : "border border-zinc-700 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {owner}
            </button>
          ))}
        </div>
      </div>
      <OwnerPostingToggles
        videoId={videoId}
        owner={selectedOwner}
        slot={ownerSlot(status, selectedOwner)}
        busyKey={busyKey}
        onToggle={toggle}
      />
      <div className="grid gap-2 border-t border-zinc-800/80 pt-3 sm:grid-cols-2">
        {OWNERS.filter((owner) => owner !== selectedOwner).map((owner) => {
          const slot = ownerSlot(status, owner);
          const used = PLATFORMS.filter((platform) => slot.effective[platform]);
          return (
            <div key={owner} className="rounded-lg border border-zinc-800/80 bg-zinc-950/40 px-3 py-2">
              <p className="text-xs font-semibold capitalize text-zinc-500">{owner}</p>
              <div className="mt-1 flex flex-wrap gap-1">
                {used.length ? (
                  used.map((platform) => <PlatformBadge key={platform} platform={platform} />)
                ) : (
                  <span className="text-xs text-zinc-600">Not marked</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {error ? <p className="text-xs text-red-300">{error}</p> : null}
    </div>
  );
}
