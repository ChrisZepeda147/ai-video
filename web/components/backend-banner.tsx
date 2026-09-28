export function BackendStatusBanner({
  kind,
  message,
}: {
  kind: "offline" | "error";
  message: string;
}) {
  const isOffline = kind === "offline";
  return (
    <div
      className={`mb-6 rounded-xl border px-4 py-3 text-sm ${
        isOffline
          ? "border-amber-500/30 bg-amber-500/10 text-amber-200"
          : "border-red-500/30 bg-red-950/30 text-red-200"
      }`}
    >
      <p className="font-medium">
        {isOffline ? "Discovery backend is offline." : "Discovery backend returned an error."}
      </p>
      <p className={`mt-1 ${isOffline ? "text-amber-200/80" : "text-red-200/80"}`}>{message}</p>
      {isOffline ? (
        <p className="mt-2 font-mono text-xs text-amber-200/70">
          npm run dev:api · npm run dev:web · npm run dev (full restart)
        </p>
      ) : (
        <p className="mt-2 text-xs text-red-200/70">
          API is running — check <code className="text-red-100">data/logs/api-dev.err</code> or restart with{" "}
          <code className="text-red-100">npm run dev</code>.
        </p>
      )}
    </div>
  );
}

/** @deprecated Use BackendStatusBanner with kind="offline" */
export function BackendOfflineBanner({ message }: { message: string }) {
  return <BackendStatusBanner kind="offline" message={message} />;
}
