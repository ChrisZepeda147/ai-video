import { Suspense } from "react";
import { AccountsWorkspace } from "@/components/accounts/accounts-workspace";
import { PublishingQueue } from "@/components/publishing/publishing-queue";
import { PageHeader } from "@/components/page-header";

export default function AccountsPage() {
  return (
    <>
      <PageHeader
        title="Accounts"
        description="Stephen or Chris — connect YouTube, TikTok, Instagram, or Facebook via real OAuth. Analytics pull from the platform after connect."
      />
      <PublishingQueue />
      <Suspense fallback={<p className="text-sm text-zinc-500">Loading accounts…</p>}>
        <AccountsWorkspace />
      </Suspense>
    </>
  );
}
