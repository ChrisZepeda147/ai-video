import { VideoDetailWorkspace } from "@/components/library/video-detail-workspace";

export default async function LibraryVideoPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const videoId = Number(id);
  return <VideoDetailWorkspace videoId={videoId} />;
}
