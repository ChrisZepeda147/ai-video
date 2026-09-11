import { PageHeader } from "@/components/page-header";
import { PreflightPanel } from "@/components/settings/preflight-panel";
import { PublishingSetupPanel } from "@/components/settings/publishing-setup-panel";
import Link from "next/link";

export default function SettingsPage() {
  return (
    <>
      <PageHeader
        title="Settings"
        description="Social OAuth setup for Chris and Stephen — 2 accounts per platform, then preflight."
      />
      <div className="mb-8">
        <PublishingSetupPanel />
      </div>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-zinc-500">System preflight</h2>
      <p className="mb-6 text-sm text-zinc-500">
        When core checks pass, start a batch on the{" "}
        <Link href="/pilot" className="text-violet-300 hover:underline">Pilot</Link> page.
      </p>
      <PreflightPanel />
    </>
  );
}
