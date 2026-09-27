import { Suspense } from "react";
import { WeeklyWorkspace } from "@/components/weekly/weekly-workspace";
import { PageHeader } from "@/components/page-header";

export default function WeeklyPage() {
  return (
    <>
      <PageHeader
        title="Weekly"
        description="Sunday: copy prompt, paste ChatGPT reply, Save week (7am auto) or Run Monday now. One day at a time after that."
      />
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading weekly plan…</p>}>
        <WeeklyWorkspace />
      </Suspense>
    </>
  );
}
