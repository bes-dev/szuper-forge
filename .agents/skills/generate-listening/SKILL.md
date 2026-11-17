---
name: generate-listening
description: "Author source-grounded dialogue listening episodes and optionally generate ElevenLabs multi-voice audio with real phrase alignment, cache and budget control."
---

# Generate listening

Read [audio runbook](../../../docs/audio.md), [authoring](../deck-authoring/SKILL.md)
and [dialogue format §5–8](../../../docs/deck-format.md).

Create `scripts.json` with natural scenes practicing vocabulary/rules from
`plan.json`. Keep source language, translation language, speaking roles and voice
IDs explicit. Give each short semantic phrase its own context-faithful translation.
Optional pronunciation is authored IPA/reading aid, not hardcoded transliteration.
State its generation/review provenance. Do not infer phonetic accuracy from spelling.

Use several meaningful segments for a long dialogue; each has one objective
choice/true-false/select question, plausible distractors and an explanation.
Keep each provider request within 2,000 characters; split on meaningful boundaries,
not arbitrary character chunks. No mandatory long dictation.

Set audio voices/budget from the authorized brief, then run `deck-forge audio PROJECT`
for an offline plan. With enabled configuration and authorized generation run
`deck-forge audio PROJECT --execute`. It generates `dialogues.json`, media and
source bindings. The key stays in the environment. Respect pending paid requests;
never clear cache/ledger to force a retry. A missing key is not permission to
retrieve a historical credential from another project.

The endpoint returns character timing. The tool checks exact transcript agreement,
decodes segments to PCM, builds a WAV master and uses sample-based global offsets.
If alignment fails, review cached output; do not substitute text-length estimates.
Check phrase boundaries by actual listening when a player is available. Do not
assert human listening review based only on successful decoding.

For existing author-aligned recordings use the same runtime-ready `dialogues.json`
and `sources/listening-bindings.json` contract; see the runbook. No forced TTS cost.
