import { Workbench } from "@/components/workbench/workbench";

export default function WorkbenchPage() {
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold text-zinc-100">Workbench</h1>
      <p className="mb-6 text-sm text-zinc-400">
        Discovery-assisted source find + Cursor generation handoff. Production pipeline stays separate.
      </p>
      <Workbench />
    </div>
  );
}
