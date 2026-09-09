import { Suspense } from "react";
import { CreateWorkspace } from "@/components/create/create-workspace";
import { PageHeader } from "@/components/page-header";

export default function CreatePage() {
  return (
    <>
      <PageHeader
        title="Create"
        description="Main production workspace — concepts, source context, generation jobs, and Cursor handoff. Study viral mechanics; generate original visuals that match mood, not every spoken line."
      />
      <Suspense
        fallback={
          <p className="text-sm text-zinc-500">Loading creative workspace…</p>
        }
      >
        <CreateWorkspace />
      </Suspense>
    </>
  );
}
