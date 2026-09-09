import { PilotWorkspace } from "@/components/pilot/pilot-workspace";
import { PageHeader } from "@/components/page-header";
import Link from "next/link";

export default function PilotPage() {
  return (
    <>
      <PageHeader
        title="Pilot"
        description="Run your first end-to-end batch — discovery through analytics. Uses existing systems; nothing auto-publishes live."
      />
      <p className="mb-6 text-sm text-zinc-500">
        Check <Link href="/settings" className="text-violet-300 hover:underline">Settings preflight</Link> first, then connect a YouTube account on{" "}
        <Link href="/accounts" className="text-violet-300 hover:underline">Accounts</Link>.
      </p>
      <PilotWorkspace />
    </>
  );
}
