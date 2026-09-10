import { MakeShortWorkspace } from "@/components/create/make-short-workspace";
import { PageHeader } from "@/components/page-header";

export default function CreatePage() {
  return (
    <>
      <PageHeader
        title="Make Short"
        description="30-second motivational Short — inspirational speech over rotating luxury visuals."
      />
      <MakeShortWorkspace />
    </>
  );
}
