---
name: verify-deck
description: "Audit and repair an authored deck, verify source coverage, identities, quizzes and media, then build a releaseable Anki .apkg with an honest validation report."
---

# Verify and release

Read [validation](../../../docs/validation.md). Run `deck-forge qa PROJECT
--check-audio` when listening exists (otherwise ordinary `qa` suffices).

Repair each concrete failure: unknown sources/quotes/IDs, uncovered inventory,
ambiguous duplicate prompts, malformed Cloze/reference/dialogue, stale scripts,
missing media and invalid timing. Do not weaken the gate, drop an entire topic or
invent an exclusion to hide an authoring error. If the source is actually missing
or undecidable, document that limitation and ask only when a user decision is needed.

Read the contents in order: titles alone should show what comes next. Inspect chapter and topic links, level labels, and the first, middle and final lessons. Review each flagged source-dependent phrase in context. Try prompts without the original material; check both directions, plausible typed variants, and an actual mistake. Resolve ambiguous prompts and unintended answer leaks. Check the complete learner-facing wording in both languages, including hints, examples and audio quiz feedback. For a small teacher lesson review every card. For a large course also sample each exercise type and review all changed or flagged patterns. State the extent of manual inspection.

Run `deck-forge build PROJECT --output PROJECT/dist/RELEASE.apkg`. It reruns QA,
builds mixed note models and checks actual ZIP/SQLite/media. Review the generated
`reports/preview.html`. If available, import into Anki and LingoDeck and exercise
one card of each kind, theory, playback/phrase replay/translation and a full quiz.

Deliver the package path, covered/excluded scope and which checks actually ran.
Do not call an unperformed device or listening check passed. A new filename is a
release, not a reason to change existing semantic IDs or GUIDs.
