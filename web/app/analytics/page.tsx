import { AnalyticsWorkspace } from "@/components/analytics/analytics-workspace";
import { PageHeader } from "@/components/page-header";

export default function AnalyticsPage() {
  return (
    <>
      <PageHeader
        title="Analytics"
        description="Track published Short performance, winning patterns, and learning signals — advisory only, not auto-creative control."
      />
      <AnalyticsWorkspace />
    </>
  );
}
