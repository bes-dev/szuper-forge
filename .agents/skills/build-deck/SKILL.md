---
name: build-deck
description: "Create or update a complete Anki/LingoDeck deck from a folder of teaching materials; orchestrate extraction, grounded authoring, optional listening, validation and packaging."
---

# Build a deck

Read [AGENTS.md](../../../AGENTS.md) and [pipeline](../../../docs/pipeline.md).
Respect the user’s requested language, level, source folder, output location and scope.

1. Find/resume the project. If new, inspect enough source material to infer the
   brief; ask only unresolved material choices. Initialize with the chosen languages.
2. Follow [audit-materials](../audit-materials/SKILL.md): extraction, unread pages,
   source evidence and plan. Save progress in artifacts, not only in conversation.
3. Read [deck-authoring](../deck-authoring/SKILL.md). Author useful Basic/Reversed/
   Cloze cards and compact theory chapters. Cover each inventory item or explicitly
   exclude it with a specific reason. Do not arbitrarily cap the whole corpus at a
   small demo count when the request asks for complete coverage.
4. If listening was requested/configured, follow
   [generate-listening](../generate-listening/SKILL.md). Scripts can reuse the same
   objectives as cards. Finish actual audio when dependencies and authorization exist.
5. Follow [verify-deck](../verify-deck/SKILL.md), fix failures and build the package.
   Report deliverables, scope and limitations. Do not end after scaffolding.

For incremental updates preserve IDs and existing source/voice decisions. Re-extract
changed sources, repair only affected content, reuse matching audio cache. Do not
reseed GUIDs or reset learner memory to make a release look new.
