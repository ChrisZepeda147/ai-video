import { Suspense } from "react";
import { WeeklyWorkspace } from "@/components/weekly/weekly-workspace";
import { PageHeader } from "@/components/page-header";

export default function WeeklyPage() {
  return (
    <>
      <PageHeader
        title="Weekly"
        description="Paste your ChatGPT week plan once. Focus one day at a time — Mon done, then Tue. 7am builds 3 videos."
      />
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading weekly plan…</p>}>
        <WeeklyWorkspace />
      </Suspense>
    </>
  );
}
