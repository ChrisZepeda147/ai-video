import { MakeShortWorkspace } from "@/components/create/make-short-workspace";
import { PageHeader } from "@/components/page-header";

export default function CreatePage() {
  return (
    <>
      <PageHeader
        title="Make Short"
        description="Structured brief → Cursor Agent builds a 9:16 Short with your audio search, visuals, and custom instructions."
      />
      <MakeShortWorkspace />
    </>
  );
}
