"use client";

import { useState } from "react";

export function ConfirmDeleteButton({
  busy = false,
  label = "Delete",
  confirmLabel = "Yes, delete files",
  hint = "Removes site row and local files.",
  onConfirm,
}: {
  busy?: boolean;
  label?: string;
  confirmLabel?: string;
  hint?: string;
  onConfirm: () => void;
}) {
  const [confirming, setConfirming] = useState(false);

  if (confirming) {
    return (
      <div className="flex flex-wrap items-center gap-2 rounded border border-red-900/60 bg-red-950/30 px-2 py-1">
        <span className="text-xs text-red-200">{hint}</span>
        <button
          type="button"
          disabled={busy}
          onClick={(e) => {
            e.stopPropagation();
            onConfirm();
          }}
          className="rounded bg-red-600 px-2 py-0.5 text-xs font-medium text-white disabled:opacity-50"
        >
          {busy ? "Deleting…" : confirmLabel}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={(e) => {
            e.stopPropagation();
            setConfirming(false);
          }}
          className="rounded border border-zinc-700 px-2 py-0.5 text-xs text-zinc-300"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <button
      type="button"
      disabled={busy}
      onClick={(e) => {
        e.stopPropagation();
        setConfirming(true);
      }}
      className="rounded border border-red-900/50 px-3 py-1 text-xs text-red-300 hover:bg-red-950/40 disabled:opacity-50"
    >
      {label}
    </button>
  );
}
