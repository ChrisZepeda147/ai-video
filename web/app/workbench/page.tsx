import { PageHeader } from "@/components/page-header";
import { Workbench } from "@/components/workbench/workbench";

export default function WorkbenchPage() {
  return (
    <>
      <PageHeader
        title="Workbench"
        description="Quick Create — find unused source audio/video or generate original AI images and clips without starting from a reference."
      />
      <Workbench />
    </>
  );
}
