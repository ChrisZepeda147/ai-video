"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { PlatformBadge } from "@/components/platform-badge";
import {
  fetchPublishingAccounts,
  fetchPublishingOwner,
  fetchPublishingSetup,
  postConnectAccount,
  postDeleteAccount,
  postVerifyAccount,
} from "@/lib/api";
import type { PublishingAccountItem, PublishingOwner, PublishingSetupResponse } from "@/lib/types";

const PLATFORMS = ["youtube", "tiktok", "instagram", "facebook"] as const;
const OWNERS: PublishingOwner[] = ["stephen", "chris"];

const PLATFORM_HINTS: Record<(typeof PLATFORMS)[number], string> = {
  youtube: "Google OAuth — channel analytics after connect",
  tiktok: "TikTok developer app — link posts for per-video stats",
  instagram: "Meta login — Business IG linked to a Page. Reels upload after reconnect.",
  facebook: "Meta login — Facebook Page. Reels upload after reconnect.",
};

export function AccountsWorkspace() {
  const searchParams = useSearchParams();
  const [accounts, setAccounts] = useState<PublishingAccountItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [localOwner, setLocalOwner] = useState<PublishingOwner>("chris");
  const [owner, setOwner] = useState<PublishingOwner>("chris");
  const [accountLabel, setAccountLabel] = useState("");
  const [setup, setSetup] = useState<PublishingSetupResponse | null>(null);
  const [backendOnline, setBackendOnline] = useState(true);

  useEffect(() => {
    fetchPublishingOwner().then((result) => {
      if (result.ok && (result.data.owner === "stephen" || result.data.owner === "chris")) {
        setLocalOwner(result.data.owner);
        setOwner(result.data.owner);
      }
    });
  }, []);

  useEffect(() => {
    fetchPublishingSetup().then((result) => {
      if (result.ok) {
        setSetup(result.data);
        setBackendOnline(true);
        return;
      }
      setBackendOnline(result.error === "offline");
      setMessage(result.message);
    });
  }, []);

  useEffect(() => {
    const fromQuery = searchParams.get("owner");
    if (fromQuery === "stephen" || fromQuery === "chris") {
      setOwner(fromQuery);
    }
  }, [searchParams]);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchPublishingAccounts({ owner });
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setAccounts(result.data.items);
  }, [owner]);

  useEffect(() => {
    void load();
  }, [load]);

  function platformReady(platform: (typeof PLATFORMS)[number]): boolean {
    return setup?.platforms[platform]?.env_ready ?? false;
  }

  async function handleConnect(platform: (typeof PLATFORMS)[number]) {
    if (busy) return;
    if (!platformReady(platform)) {
      setMessage(
        `Add ${setup?.platforms[platform]?.env_keys.join(", ") ?? "developer app keys"} to scripts/.env first — see Settings.`,
      );
      return;
    }
    setBusy(true);
    setMessage(null);
    const redirectUri = `${window.location.origin}/accounts/callback`;
    const label = accountLabel.trim() || `${owner} ${platform}`;
    const result = await postConnectAccount(platform, {
      display_name: label,
      owner,
      redirect_uri: redirectUri,
    });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    window.location.href = result.data.auth_url;
  }

  return (
    <div className="space-y-6">
      {!backendOnline ? (
        <div className="rounded-xl border border-red-500/40 bg-red-950/30 p-4 text-sm text-red-200">
          Discovery backend is offline. From repo root run <code className="text-red-100">npm run dev</code> and wait
          for API on port 8000.
        </div>
      ) : null}
      {setup && setup.gaps.some((g) => g.includes("credentials missing")) ? (
        <div className="rounded-xl border border-amber-500/40 bg-amber-950/30 p-4 text-sm text-amber-100">
          Developer app keys missing in <code className="text-amber-50">scripts/.env</code>. Connect buttons stay
          disabled until you add them. Open{" "}
          <Link href="/settings" className="underline">
            Settings → Publishing setup
          </Link>{" "}
          for the checklist and redirect URI.
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-zinc-800 p-1">
          {OWNERS.map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setOwner(name)}
              className={`rounded-md px-3 py-1.5 text-sm capitalize ${
                owner === name ? "bg-violet-600 text-white" : "text-zinc-400 hover:text-zinc-200"
              }`}
            >
              {name}
            </button>
          ))}
        </div>
        {owner !== localOwner ? (
          <p className="text-xs text-zinc-500">
            Viewing {owner}&apos;s accounts — OAuth still runs on this machine.
          </p>
        ) : (
          <p className="text-xs text-zinc-500">
            This machine: <span className="capitalize text-zinc-300">{localOwner}</span>
          </p>
        )}
        <Link href="/settings" className="text-xs text-violet-300 underline">
          OAuth setup checklist
        </Link>
      </div>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h2 className="text-sm font-semibold text-zinc-200">Connect {owner}&apos;s accounts</h2>
        <p className="mt-1 text-xs text-zinc-500">
          Connect up to 2 accounts per platform for {owner}. Label each channel, then click a platform — OAuth opens on
          the real site. Tokens stay in <code className="text-zinc-400">data/publishing/credentials/</code>.
        </p>
        <label className="mt-3 block text-xs text-zinc-400">
          Account label (optional — use for 2nd channel)
          <input
            value={accountLabel}
            onChange={(e) => setAccountLabel(e.target.value)}
            placeholder={`e.g. ${owner} main, ${owner} backup`}
            className="mt-1 w-full max-w-md rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm text-zinc-100"
          />
        </label>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {PLATFORMS.map((platform) => {
            const ready = platformReady(platform);
            return (
              <button
                key={platform}
                type="button"
                disabled={busy || !ready}
                onClick={() => void handleConnect(platform)}
                className="rounded-xl border border-zinc-700 bg-zinc-950/60 p-4 text-left transition hover:border-violet-500/50 hover:bg-zinc-900 disabled:opacity-50"
              >
                <PlatformBadge platform={platform} />
                <p className="mt-2 text-sm font-medium capitalize text-zinc-100">Connect {platform}</p>
                <p className="mt-1 text-xs text-zinc-500">{PLATFORM_HINTS[platform]}</p>
                {!ready ? (
                  <p className="mt-2 text-xs text-amber-300">Add keys in scripts/.env first</p>
                ) : null}
              </button>
            );
          })}
        </div>
      </section>

      {message ? <p className="text-sm text-amber-300">{message}</p> : null}

      {loading ? (
        <p className="text-sm text-zinc-500">Loading accounts…</p>
      ) : (
        PLATFORMS.map((platform) => {
          const grouped = accounts.filter((a) => a.platform === platform);
          return (
            <section key={platform} className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
              <div className="mb-3 flex items-center gap-2">
                <PlatformBadge platform={platform} />
                <span className="text-xs text-zinc-500">
                  {grouped.length} connected for {owner}
                </span>
              </div>
              {grouped.length === 0 ? (
                <p className="text-sm text-zinc-600">No {platform} accounts for {owner} yet.</p>
              ) : (
                <ul className="space-y-3">
                  {grouped.map((a) => (
                    <li key={a.id} className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="font-medium text-zinc-100">{a.display_name}</p>
                          <p className="text-xs text-zinc-500">
                            <span className="capitalize">{a.owner || owner}</span> · @{a.username || "—"} ·{" "}
                            {a.auth_status}
                            {a.niche ? ` · ${a.niche}` : ""}
                          </p>
                          <p className="mt-1 text-xs text-zinc-600">
                            Analytics: {a.auth_status === "connected" || a.auth_status === "verified" ? "ready" : "needs reconnect"}
                            {" · "}
                            Posting: {a.posting_available ? "ready" : "reconnect for Reels"}
                            {a.last_verified_at ? ` · verified ${new Date(a.last_verified_at).toLocaleString()}` : ""}
                          </p>
                          {a.audit_note ? (
                            <p className="mt-2 text-xs text-amber-400/90">{a.audit_note}</p>
                          ) : null}
                        </div>
                        <div className="flex gap-2">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              await postVerifyAccount(a.id);
                              setBusy(false);
                              await load();
                            }}
                            className="rounded border border-zinc-700 px-2 py-1 text-xs disabled:opacity-50"
                          >
                            Refresh
                          </button>
                          <button
                            type="button"
                            disabled={busy}
                            onClick={async () => {
                              setBusy(true);
                              await postDeleteAccount(a.id);
                              setBusy(false);
                              await load();
                            }}
                            className="rounded border border-red-500/30 px-2 py-1 text-xs text-red-300 disabled:opacity-50"
                          >
                            Disconnect
                          </button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          );
        })
      )}
    </div>
  );
}
