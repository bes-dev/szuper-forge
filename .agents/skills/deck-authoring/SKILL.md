---
name: deck-authoring
description: "Shared LingoDeck authoring knowledge: atomic source-grounded Anki cards, HTML theory, dialogue episodes, stable identity and language-independent data."
---

# Shared deck authoring

Read [format specification](../../../docs/deck-format.md) and
[artifact schemas](../../../docs/pipeline.md) as needed. Ordinary notes require no
LingoDeck custom model: Basic/Reversed/Cloze plus topic tags are enough. Dialogue
and reference are optional extensions with Front in field 0 and HTML in field 1.

- Ask one clear question about one contextualized meaning. Put all valid short
  answer variants on Back; avoid merging unrelated senses. Reverse only unambiguous
  pairs. Use Cloze for application/context rather than copying a whole textbook.
- Hint is pedagogical assistance. Source is evidence/provenance generated from
  plan references; technical labels and file names do not belong in Hint/TTS.
- A normal tag is a topic. Use `::` nesting and `_` for spaces. A note may belong
  to several topics without duplicate memory. Do not create gated levels/stages.
- Theory is `kind: reference`, a focused HTML explanation with headings, examples
  and tables. The builder adds reference/theory tags. Local media only, no JS or
  network-dependent HTML. Do not create dictionary/archive menus from metadata.
- New dialogue lessons use one note for the full episode, one master recording,
  timed phrases, per-phrase translation and an authored comprehension quiz. One
  completed episode creates one FSRS review. The app owns UI/UX; do not reproduce
  its controls in arbitrary JavaScript templates.
- All source/translation language codes, speaker names, text and pronunciation
  come from the authored data. No application-wide Hungarian/Russian defaults.
- Keep project uid/deck/model IDs, semantic note IDs and explicit legacy GUIDs.
  Updating text or tags must preserve identity. V1 phrase IDs are positional, so
  inserting/reordering phrases affects an in-progress checkpoint.

Authors may create new practice contexts, but label them as authored scenes and
verify that they practice the source objectives. Do not attribute invented facts
or quotations to the source. Never claim generated IPA is human-checked.
