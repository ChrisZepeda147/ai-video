import { PageHeader } from "@/components/page-header";
import { PublishingQueue } from "@/components/publishing/publishing-queue";
import { VideosWorkspace } from "@/components/videos/videos-workspace";

export default function VideosPage() {
  return (
    <>
      <PageHeader
        title="Videos"
        description="All finished Shorts — site pipeline and legacy renders from Stephen's scripts, in one library."
      />
      <PublishingQueue />
      <VideosWorkspace />
    </>
  );
}
