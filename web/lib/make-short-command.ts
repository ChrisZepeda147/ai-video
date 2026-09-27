/** Compose a Make Short form into a Cursor Agent command. Keep in sync with scripts/discovery/motivation_command_brief.py */

export type MakeShortOwner = "chris" | "stephen";

export type MakeShortCommandInput = {
  owner?: MakeShortOwner;
  audioQuery?: string;
  brollQuery: string;
  instructions?: string;
  minSeconds?: number;
  maxSeconds?: number;
};

function visualProductionHints(visual: string): string[] {
  const text = visual.trim();
  if (!text) return [];
  const hints: string[] = [];
  if (/\b(view|ocean|skyline|apartment|penthouse|drone)\b/i.test(text)) {
    hints.push(
      "View / scenery B-roll: no people in frame; use exclude-people / view-only search; 50fps+ clips only.",
    );
  }
  if (/\b(porsche|ferrari|911|gt3|supercar|coupe|lamborghini)\b/i.test(text)) {
    hints.push("Car B-roll: exterior only for opener (full body 5s+); no cabin/dashboard; 50fps+ source clips.");
  }
  return hints;
}

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
    "- Check combinations catalog / existing transcripts — skip the same excerpt unless Extra instructions allow a remake.",
    "- Set speaker from actual clip title/channel (not search query). If search was Goggins but clip is Jocko, register as Jocko Willink.",
    "- Reuse of prior sources is allowed by default. Unused-only only if Extra instructions say unused / never used.",
    "",
  ];

  if (audio) {
    lines.push(`Search for audio (any type — speech, podcast clip, interview, etc.): ${audio}`);
  } else {
    lines.push("Search for audio: pick fitting motivational audio (any type — not limited to speeches).");
  }

  lines.push(`Visual / B-roll search: ${broll}`);
  lines.push(`Default target length: ${minSec}–${maxSec} seconds unless extra instructions override.`);

  for (const hint of visualProductionHints(broll)) {
    lines.push(`- ${hint}`);
  }

  if (extra) {
    lines.push("", "Extra instructions:", extra);
  }

  lines.push(
    "",
    "Before downloading audio, query the production library and check existing transcripts — skip the same excerpt unless Extra instructions allow a remake.",
    "Register the finished video in the production library when done.",
  );

  return lines.join("\n");
}
