"use client";

import { useCallback, useEffect, useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import {
  fetchPublishingAccounts,
  postConnectAccount,
  postCreateMockAccount,
  postDeleteAccount,
  postVerifyAccount,
} from "@/lib/api";
import type { PublishingAccountItem } from "@/lib/types";

const PLATFORMS = ["youtube", "tiktok", "instagram"] as const;

export function AccountsWorkspace() {
  const [accounts, setAccounts] = useState<PublishingAccountItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [connectName, setConnectName] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchPublishingAccounts();
    setLoading(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setAccounts(result.data.items);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function handleConnect(platform: string) {
    if (!connectName.trim() || busy) return;
    setBusy(true);
    setMessage(null);
    const result = await postConnectAccount(platform, { display_name: connectName.trim() });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    if (result.data.instructions) {
      setMessage(result.data.instructions);
    }
    window.open(result.data.auth_url, "_blank", "noopener,noreferrer");
    setMessage(
      `OAuth opened for ${platform}. After approving, complete connection with the callback code via API or use Mock Connect for local dev.`,
    );
  }

  async function handleMockConnect(platform: string) {
    if (!connectName.trim() || busy) return;
    setBusy(true);
    const result = await postCreateMockAccount(platform, { display_name: connectName.trim() });
    setBusy(false);
    if (!result.ok) {
      setMessage(result.message);
      return;
    }
    setMessage(`Mock ${platform} account connected: ${result.data.display_name}`);
    setConnectName("");
    await load();
  }

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h2 className="text-sm font-semibold text-zinc-200">Connect account</h2>
        <p className="mt-1 text-xs text-zinc-500">
          OAuth tokens are stored locally in <code className="text-zinc-400">data/publishing/credentials/</code> — never committed to Git.
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={connectName}
            onChange={(e) => setConnectName(e.target.value)}
            placeholder="Display name (e.g. LuxuryMindset)"
            className="min-w-[220px] flex-1 rounded border border-zinc-700 bg-zinc-950 px-3 py-2 text-sm"
          />
          {PLATFORMS.map((p) => (
            <button
              key={p}
              type="button"
              disabled={busy || !connectName.trim()}
              onClick={() => handleConnect(p)}
              className="rounded border border-zinc-700 px-3 py-2 text-xs capitalize disabled:opacity-50"
            >
              Connect {p}
            </button>
          ))}
          {PLATFORMS.map((p) => (
            <button
              key={`mock-${p}`}
              type="button"
              disabled={busy || !connectName.trim()}
              onClick={() => handleMockConnect(p)}
              className="rounded border border-violet-500/40 bg-violet-600/10 px-3 py-2 text-xs capitalize text-violet-300 disabled:opacity-50"
            >
              Mock {p}
            </button>
          ))}
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
                <span className="text-xs text-zinc-500">{grouped.length} connected</span>
              </div>
              {grouped.length === 0 ? (
                <p className="text-sm text-zinc-600">No {platform} accounts connected.</p>
              ) : (
                <ul className="space-y-3">
                  {grouped.map((a) => (
                    <li key={a.id} className="rounded-lg border border-zinc-800 bg-zinc-950/50 p-3">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div>
                          <p className="font-medium text-zinc-100">{a.display_name}</p>
                          <p className="text-xs text-zinc-500">
                            @{a.username || "—"} · {a.auth_status}
                            {a.niche ? ` · ${a.niche}` : ""}
                          </p>
                          <p className="mt-1 text-xs text-zinc-600">
                            Posting: {a.posting_available ? "available" : "restricted"}
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
                            Verify
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
