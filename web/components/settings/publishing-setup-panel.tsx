"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { PlatformBadge } from "@/components/platform-badge";
import { fetchPublishingSetup } from "@/lib/api";
import type { PublishingSetupResponse } from "@/lib/types";

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      className="rounded border border-zinc-700 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-800"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function PublishingSetupPanel() {
  const [data, setData] = useState<PublishingSetupResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const result = await fetchPublishingSetup();
    setLoading(false);
    if (!result.ok) {
      setError(result.message);
      return;
    }
    setData(result.data);
    setError(null);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) return <p className="text-sm text-zinc-500">Loading publishing setup…</p>;
  if (error) return <p className="text-sm text-red-400">{error}</p>;
  if (!data) return null;

  const platforms = Object.entries(data.platforms);

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-violet-500/30 bg-violet-950/20 p-4">
        <h3 className="text-sm font-semibold text-violet-200">Chris + Stephen — 2 accounts each</h3>
        <p className="mt-2 text-sm text-zinc-400">{data.brother_note}</p>
        <ul className="mt-3 list-inside list-disc space-y-1 text-xs text-zinc-500">
          <li>
            <strong className="text-zinc-300">Stephen&apos;s PC:</strong>{" "}
            <code className="text-zinc-400">PUBLISHING_OWNER=stephen</code> +{" "}
            <code className="text-zinc-400">SHARED_LIBRARY_EXPORT_OWNER=stephen</code>
          </li>
          <li>
            <strong className="text-zinc-300">Chris&apos;s PC:</strong>{" "}
            <code className="text-zinc-400">PUBLISHING_OWNER=chris</code> (default)
          </li>
          <li>
            Put shared developer keys once in <code className="text-zinc-400">scripts/.env</code> on each machine (same
            Google/Meta/TikTok apps, never commit)
          </li>
          <li>
            On <Link href="/accounts" className="text-violet-300 underline">Accounts</Link>, pick owner tab → connect{" "}
            {data.target_accounts_per_owner} accounts per platform with a label each
          </li>
        </ul>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-sm font-semibold text-zinc-200">OAuth redirect URI</h3>
          <CopyButton value={data.oauth_redirect_uri} />
        </div>
        <p className="mt-2 font-mono text-xs text-emerald-300">{data.oauth_redirect_uri}</p>
        <p className="mt-2 text-xs text-zinc-500">
          Register this exact URL in Google Cloud, TikTok Login Kit, and Meta Facebook Login.
        </p>
        {(data.mock_provider || data.dry_run) && (
          <p className="mt-2 text-xs text-amber-300">
            {data.mock_provider ? "DISCOVERY_PUBLISH_PROVIDER=mock blocks real OAuth. " : ""}
            {data.dry_run ? "DISCOVERY_PUBLISH_DRY_RUN is on. " : ""}
            Unset both for live analytics.
          </p>
        )}
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h3 className="text-sm font-semibold text-zinc-200">Developer app credentials</h3>
        <p className="mt-1 text-xs text-zinc-500">
          Machine owner: <span className="capitalize text-zinc-300">{data.machine_owner}</span>
        </p>
        <ul className="mt-3 space-y-3">
          {platforms.map(([key, platform]) => (
            <li key={key} className="rounded-lg border border-zinc-800 px-3 py-2">
              <div className="flex flex-wrap items-center gap-2">
                <PlatformBadge platform={key} />
                <span
                  className={`text-[10px] font-bold uppercase ${
                    platform.env_ready ? "text-emerald-300" : "text-red-300"
                  }`}
                >
                  {platform.env_ready ? "configured" : "missing keys"}
                </span>
              </div>
              <p className="mt-1 text-xs text-zinc-500">{platform.notes}</p>
              <p className="mt-1 font-mono text-[11px] text-zinc-600">{platform.env_keys.join(", ")}</p>
              <a
                href={platform.portal_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 inline-block text-xs text-violet-300 underline"
              >
                Open developer portal
              </a>
            </li>
          ))}
        </ul>
      </section>

      <section className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-4">
        <h3 className="text-sm font-semibold text-zinc-200">Connected accounts matrix</h3>
        <p className="mt-1 text-xs text-zinc-500">
          Target: {data.target_accounts_per_owner} connected accounts per platform per owner
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-xs">
            <thead>
              <tr className="text-zinc-500">
                <th className="pb-2 pr-3">Owner</th>
                {platforms.map(([key]) => (
                  <th key={key} className="pb-2 pr-3 capitalize">
                    {key}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.owners.map((owner) => (
                <tr key={owner} className="border-t border-zinc-800/80">
                  <td className="py-2 pr-3 capitalize text-zinc-300">{owner}</td>
                  {platforms.map(([key]) => {
                    const cell = data.account_matrix[owner]?.[key];
                    const connected = cell?.connected ?? 0;
                    const target = cell?.target ?? data.target_accounts_per_owner;
                    const ok = connected >= target;
                    return (
                      <td key={key} className={`py-2 pr-3 ${ok ? "text-emerald-300" : "text-amber-300"}`}>
                        {connected}/{target}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {data.gaps.length > 0 ? (
        <section className="rounded-xl border border-amber-500/30 bg-amber-950/20 p-4">
          <h3 className="text-sm font-semibold text-amber-200">Still needed</h3>
          <ul className="mt-2 list-inside list-disc space-y-1 text-xs text-amber-100/90">
            {data.gaps.map((gap) => (
              <li key={gap}>{gap}</li>
            ))}
          </ul>
        </section>
      ) : (
        <p className="text-sm text-emerald-300">All setup checks passed — connect any remaining accounts on Accounts.</p>
      )}

      <div className="flex gap-2">
        <Link href="/accounts" className="rounded bg-violet-600 px-3 py-2 text-sm text-white">
          Open Accounts
        </Link>
        <button
          type="button"
          onClick={() => void load()}
          className="rounded border border-zinc-700 px-3 py-2 text-sm text-zinc-300"
        >
          Refresh
        </button>
      </div>
    </div>
  );
}
