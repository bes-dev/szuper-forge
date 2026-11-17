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

Inspect the authored content against sources: exact senses, contextual translations,
quiz correctness, natural scenes and mobile-readable theory. Local gates do not
prove those properties automatically. Revisit affected material after corrections.

Run `deck-forge build PROJECT --output PROJECT/dist/RELEASE.apkg`. It reruns QA,
builds mixed note models and checks actual ZIP/SQLite/media. Review the generated
`reports/preview.html`. If available, import into Anki and LingoDeck and exercise
one card of each kind, theory, playback/phrase replay/translation and a full quiz.

Deliver the package path, covered/excluded scope and which checks actually ran.
Do not call an unperformed device or listening check passed. A new filename is a
release, not a reason to change existing semantic IDs or GUIDs.
