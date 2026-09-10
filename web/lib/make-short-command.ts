/** Compose a Make Short form into a Cursor Agent command. */

export type MakeShortOwner = "chris" | "stephen";

export type MakeShortCommandInput = {
  owner?: MakeShortOwner;
  audioQuery?: string;
  brollQuery: string;
  instructions?: string;
  minSeconds?: number;
  maxSeconds?: number;
};

export function composeMakeShortCommand(input: MakeShortCommandInput): string {
  const audio = input.audioQuery?.trim();
  const broll = input.brollQuery.trim();
  const extra = input.instructions?.trim();
  const minSec = input.minSeconds ?? 60;
  const maxSec = input.maxSeconds ?? 90;

  const owner = input.owner ?? "chris";

  const lines = [
    "Make a new 9:16 motivational Short using the luxury-clips-montage workflow.",
    "Run `python scripts/build_motivation_job.py` with appropriate flags — do not reimplement FFmpeg or download logic.",
    `Owner account: ${owner} — record combination usage for this owner when done.`,
    "",
    "Before picking audio or visuals:",
    "- Query production library: `python scripts/production_library_cli.py list`",
    "- Check combinations catalog / existing transcripts — do not reuse the same excerpt unless instructions allow.",
    "- Set speaker from actual clip title/channel (not search query). If search was Goggins but clip is Jocko, register as Jocko Willink.",
    "- Use `--reuse-policy require_new` when instructions say do not reuse.",
    "",
  ];

  if (audio) {
    lines.push(`Search for audio (any type — speech, podcast clip, interview, etc.): ${audio}`);
  } else {
    lines.push("Search for audio: pick fitting motivational audio (any type — not limited to speeches).");
  }

  lines.push(`Visual / B-roll search: ${broll}`);
  lines.push(`Default target length: ${minSec}–${maxSec} seconds unless extra instructions override.`);

  if (extra) {
    lines.push("", "Extra instructions:", extra);
  }

  lines.push(
    "",
    "Before downloading audio, query the production library and check existing transcripts — avoid reusing the same excerpt unless instructions say otherwise.",
    "Register the finished video in the production library when done.",
  );

  return lines.join("\n");
}
