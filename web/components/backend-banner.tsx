export function BackendOfflineBanner({ message }: { message: string }) {
  return (
    <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
      <p className="font-medium">Discovery backend is offline.</p>
      <p className="mt-1 text-amber-200/80">{message}</p>
      <p className="mt-2 font-mono text-xs text-amber-200/70">
        python -m uvicorn api.main:app --reload --port 8000
      </p>
    </div>
  );
}
