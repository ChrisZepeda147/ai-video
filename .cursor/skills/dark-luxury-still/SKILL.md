---
name: dark-luxury-still
description: Generates dark-luxury cinematic stills in a charcoal look with a light plum cast. Time of day and fog are set per shot. Use when the user asks for a dark luxury still, fog car photo, moody driveway photo, yacht still, or to recreate that reference aesthetic.
---

# Dark luxury still

Read `prompts/dark-luxury-still.md` and `prompts/dark-luxury-still/references/SOURCES.md` before generating.

## How to generate

1. Take SUBJECT, SETTING, TIME, and ATMOSPHERE from the user. Defaults: original cars/house, TIME=dusk, ATMOSPHERE=light.
2. Check reuse first: `python scripts/content_reuse.py check-photo --slug "<filename-stem>" --subject "<SUBJECT> <SETTING>"`. If it fails, change the subject/setting. Do not regenerate or save over an existing still.
3. Always attach the mood lock: `c:/Users/Zev/Desktop/Ai-Video/prompts/dark-luxury-still/reference.png`
4. Also attach 1–2 extra refs from `prompts/dark-luxury-still/references/` that match the subject. Do not attach more than 3 images total.
5. Extra refs are for **subject and setting variety only**. Do not copy their headlights, warm interiors, sunny color, people, or logos.
6. Call GenerateImage with:
   - `aspect_ratio`: `9:16` unless the user asks otherwise
   - `reference_image_paths`: mood lock + matching extras
   - `description`: the copy-paste prompt from `prompts/dark-luxury-still.md` with SUBJECT, SETTING, TIME, and ATMOSPHERE filled in
7. Save a copy into `prompts/dark-luxury-still/` with a new slug and generate one still unless they ask for a series. Then run `python scripts/content_reuse.py rebuild`.

## Extra ref picker

- House / mansion → `house-luxury-dusk.jpg` or `house-luxury-pool-dusk.jpg`
- Forest house → `house-modern-fog.jpg` + `house-glass-woods.jpg`
- Sports car → `car-black-sports-dusk.jpg` or `car-porsche-night.jpg`
- SUV → `car-luxury-suv-modern.jpg`
- Forest / road → `road-forest-fog.jpg`
- Yacht / water / Bugatti on a boat → `supercar-marina.jpg` + `boat-fog-water.jpg`
- Wide yacht → `yachts-night-marina.jpg` + `boat-fog-water.jpg`

## Time

Honor TIME. Default dusk if blank.

| TIME | How it should read |
|---|---|
| dawn | Cool, pale, just before sunrise |
| morning | Soft daylight, still underexposed, not sunny HDR |
| overcast day | Flat gray daylight, place stays readable |
| golden hour | Low sun, warm edges only — keep the grade charcoal, not orange |
| dusk | Last light, default look |
| blue hour | After sunset, cool sky, no streetlights |
| night | Dark sky, house and cars still readable, no headlights or streetlights |
| midnight | Near-black, almost no ambient, only faint sky |

## Atmosphere

Fog helps, but do not put it on every still.

- Use fog when the user asks for it, or when a void/mystery helps (empty driveway, water, forest edge).
- Skip or keep it light when the place should stay readable (LA mansion, yacht, specific house).
- If the user does not say, vary it. Default to light atmosphere, not a full white-out.

## Locked look

Do not change these:

- Mostly charcoal / slate / black, with a light plum cast — not a purple wash
- Honor TIME. Still underexposed and quiet — no sunny HDR
- No headlights, no streetlights, no warm lamps unless TIME needs the house to stay readable
- Quiet dark-luxury mood, glossy wet-looking surfaces
- Soft focus, grainy film texture, not sharp HDR
- When fog is used: cool gray with a hint of violet, never a purple wash or navy cyan
- Wide / pulled-back framing unless the user asks for a close-up
- No text, no invented logos, no extra props, no people unless asked
- Match the original mood more than the extra refs
