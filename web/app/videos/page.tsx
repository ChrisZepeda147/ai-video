import { PageHeader } from "@/components/page-header";
import { PublishingQueue } from "@/components/publishing/publishing-queue";
import { VideosWorkspace } from "@/components/videos/videos-workspace";

export default function VideosPage() {
  return (
    <>
      <PageHeader
        title="Videos"
        description="Finished 9:16 Short production projects — preview, re-render, review, and publishing queue."
      />
      <PublishingQueue />
      <VideosWorkspace />
    </>
  );
}
