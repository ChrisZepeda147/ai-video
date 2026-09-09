import { AccountsWorkspace } from "@/components/accounts/accounts-workspace";
import { PublishingQueue } from "@/components/publishing/publishing-queue";
import { PageHeader } from "@/components/page-header";

export default function AccountsPage() {
  return (
    <>
      <PageHeader
        title="Accounts"
        description="Connect YouTube, TikTok, and Instagram publishing accounts. Tokens stay local — never in Git."
      />
      <PublishingQueue />
      <AccountsWorkspace />
    </>
  );
}
