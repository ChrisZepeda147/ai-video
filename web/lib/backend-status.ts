import type { ApiResult } from "@/lib/types";

export type BackendProbe = {
  online: boolean;
  dataError: string | null;
};

/** True API down vs running but a data endpoint failed. */
export function resolveBackendProbe(
  health: ApiResult<{ status: string }>,
  ...dataResults: ApiResult<unknown>[]
): BackendProbe {
  const online = health.ok && health.data.status === "ok";
  if (!online) {
    return { online: false, dataError: null };
  }
  for (const result of dataResults) {
    if (!result.ok) {
      return { online: true, dataError: result.message };
    }
  }
  return { online: true, dataError: null };
}
