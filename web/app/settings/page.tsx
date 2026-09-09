import { PageHeader } from "@/components/page-header";
import { PreflightPanel } from "@/components/settings/preflight-panel";
import Link from "next/link";

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Preflight checks before your first real pilot run."
      />
      <p className="mb-6 text-sm text-zinc-500">
        When core checks pass, start a batch on the{" "}
        <Link href="/pilot" className="text-violet-300 hover:underline">Pilot</Link> page.
      </p>
      <PreflightPanel />
    </>
  );
}
