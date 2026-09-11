import { AnalyticsWorkspace } from "@/components/analytics/analytics-workspace";
import { PageHeader } from "@/components/page-header";

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Analytics"
        description="Stephen and Chris — separate YouTube, TikTok, and Instagram analytics. Link live posts from Videos; in-app upload comes later."
      />
      <AnalyticsWorkspace />
    </>
  );
}
