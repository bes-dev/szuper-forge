---
name: build-deck
description: Create or update an Anki/LingoDeck .apkg from teacher notes, a lesson, or course materials. Use for personal lesson updates and complete ordered courses, including optional listening.
---

# Build or update a deck

Start from what the learner wants to recall. Use the languages, scope, existing project and output location in the request. Ask only when an unresolved choice would materially change the deck.

1. **Select.** For a teacher session, prioritize corrections, phrases the learner tried to say, and the teacher's assignments. For a course or exam, map objectives and prerequisites across the requested material. An explicit request for every vocabulary item overrides selection by usefulness.
2. **Author.** Resume the existing project. Extract changed inputs and record evidence locally. Use the [editorial guide](../deck-authoring/SKILL.md) for titles, order, card design and incremental edits. Use [source audit](../audit-materials/SKILL.md) for unread pages or coverage problems. The [pipeline](../../../docs/pipeline.md) gives the commands and JSON shapes.
3. **Deliver.** Build a versioned package using [release verification](../verify-deck/SKILL.md). Give the learner the file, a brief account of additions/changes/omissions and any genuinely unverified results. The preview should make sense to someone who has never seen the inputs.

The user's current agent authors the content. Add [listening](../generate-listening/SKILL.md) when requested, using existing recordings or an explicitly authorized synthesis budget. Ordinary lessons need neither a voice provider nor a separate LLM key.
