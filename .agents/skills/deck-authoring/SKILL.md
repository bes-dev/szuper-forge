---
name: deck-authoring
description: Turn grounded material into standalone, ordered LingoDeck lessons with clear titles, fair typed answers, theory linked to practice, and stable identity across updates.
---

# Write for the learner

## Choose the unit of learning

For a **lesson with a teacher**, ask what the learner should be able to say or recognize tomorrow. Use their actual mistakes and the teacher's correction. Add the smallest set of prompts that practices those distinctions. A handful of phrases can be a complete lesson. Add a theory page when an explanation will help.

For a **course**, group by communicative aim or concept. Introduce a distinction, practice it in context, then reuse it in a later task. Split a chapter when the learner is switching skills; combine fragments that make sense only together. Keep useful exam lists intact in the reference chapter and test meaningful subsets or individual distinctions. If full vocabulary coverage was requested, retain it in themed vocabulary practice, including the requested word forms.

## Make the contents read like a textbook

Use the learner's interface language for section and lesson names unless requested otherwise. Choose one naming pattern for parallel items: “Поздороваться и попрощаться”, “Заказать напиток”, “Попросить счёт”. For a reference subject a concrete noun phrase works: “Образование Будапешта”. A section groups several related lessons. A glossary earns a separate entry when learners will actually use it.

For a levelled language course, use an estimated CEFR level or range consistently across topics, theory and listening: `A2 · Перенести встречу`, `A2–B1 · ПМЖ · Символы Венгрии`. A level describes the language demand. Keep lesson numbers, filenames, PDF pages and production labels out of titles. Preserve meaningful dates and numbers (“Революция 1956 года”). For unlevelled or non-language material use subject titles.

In an ordered textbook, give each theory chapter a matching Front and visible heading. Use the same topic on its cards, e.g. `lingodeck::topic::A2_·_Перенести_встречу`. Set `lingodeck::section::<name>`, `lingodeck::course-order::<N>` for the topic/section sequence and `lingodeck::order::<N>` for within-section reading order. Leave room between ranks. Today uses the topic sequence and advances after all active cards in the topic have been seen. A stable `lingodeck::practice::<key>` on the chapter and its ordinary cards links reading to exercises. Keep that key through renames. For an episode align Front, dialogue title, level and order. Use the [format contract](../../../docs/deck-format.md) for special cases.

## Write one answerable prompt at a time

- State the situation and ask for one recall decision. “Where do I go? Put Budapest in the destination form” → `Budapestre`. “Where am I? Put Budapest in the location form” → `Budapesten`. If the learner already knows the second form, only add the first. A cloze in a complete sentence can target the same contrast.
- Put the shortest sufficient answer on Back, a useful cue in Hint, and the explanation or a bilingual example after the answer. Read each question without its heading, adjacent cards, handout or picture. A picture-dependent question needs the actual local image. Rewrite “Which town is named on slide 4?” around the event or property being learned.
- Test production only where the expected wording is sufficiently constrained. LingoDeck typed input accepts interchangeable variants separated by `/` or `;`. A comma can be interpreted as a set and a subset as partial recall. Use those separators deliberately. Compare an expected answer, a reasonable alternative, and a genuinely wrong answer; account for the deck's diacritic setting. Option selection uses exact matching. Reverse a note only if both directions have useful, fair prompts. Keep wrong options plausible in context.
- Make theory easy to read on a phone: a short explanation, an example with translation where useful, then a way to practice. Group vocabulary by topic or alphabetically. Keep source quotations, page references and editorial decisions in the project. Give changing facts a date and preserve uncertainty. Public attribution required for reused material must still accompany it.
- For full audio, keep the existing [episode workflow](../generate-listening/SKILL.md): real audio, timed phrases, contextual translations and an answerable comprehension question. An authored scene may illustrate a source objective; the scene itself is authored material.

## Update in place

Compare proposed prompts with existing meanings, both directions and nearby topics. Reuse an existing note for the same recall target; add a tag or example if useful. A different sense or skill may deserve its own note. Preserve project/deck/model IDs, semantic IDs, GUIDs and audio/phrase identities. Never repurpose a reviewed card for an unrelated fact. If a dated fact changes, make the time frame explicit. Report changes relative to the previous version and explain deliberately omitted material.
