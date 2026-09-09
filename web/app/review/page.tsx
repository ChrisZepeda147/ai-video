import { ReviewWorkspace } from "@/components/review/review-workspace";
import { PageHeader } from "@/components/page-header";

export default function ReviewPage() {
  return (
    <>
      <PageHeader
        title="Review"
        description="Review AI visual assets and finished Shorts. Approve visuals for assembly; approve finished Shorts to mark source content as globally used."
      />
      <ReviewWorkspace />
    </>
  );
}
