"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { postCompleteAccountConnect } from "@/lib/api";

export function AccountsCallback() {
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("Completing connection…");

  useEffect(() => {
    const code = searchParams.get("code");
    const state = searchParams.get("state");
    const error = searchParams.get("error");
    const errorDescription = searchParams.get("error_description");

    if (error) {
      setStatus("error");
      setMessage(errorDescription || error);
      return;
    }
    if (!code || !state) {
      setStatus("error");
      setMessage("Missing OAuth code or state. Start connect again from Accounts.");
      return;
    }

    let cancelled = false;
    void (async () => {
      const result = await postCompleteAccountConnect({ code, state });
      if (cancelled) return;
      if (!result.ok) {
        setStatus("error");
        setMessage(result.message);
        return;
      }
      const owner = result.data.owner || "chris";
      setStatus("ok");
      setMessage(`Connected ${result.data.display_name} on ${result.data.platform}.`);
      window.setTimeout(() => {
        window.location.href = `/accounts?owner=${owner}`;
      }, 1200);
    })();

    return () => {
      cancelled = true;
    };
  }, [searchParams]);

  return (
    <div className="mx-auto max-w-lg rounded-xl border border-zinc-800 bg-zinc-900/40 p-6 text-center">
      <p
        className={`text-sm ${
          status === "error" ? "text-red-300" : status === "ok" ? "text-emerald-300" : "text-zinc-300"
        }`}
      >
        {message}
      </p>
      {status === "error" ? (
        <Link href="/accounts" className="mt-4 inline-block text-sm text-violet-300 underline">
          Back to Accounts
        </Link>
      ) : null}
    </div>
  );
}
