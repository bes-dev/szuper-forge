# Validation and practical limits

## What automated checks establish

- Input JSON follows strict artifact schemas; unknown keys are rejected.
- Every inventoried source is used or explicitly excluded; unread sources block
  release unless excluded. Actual files still match their extracted content hashes.
- Every plan objective has evidence that occurs on its referenced source page.
- Every emitted note/episode maps to real plan items; no uncovered item disappears
  silently. Exclusions remain visible and lower the reported inventory coverage.
- Semantic IDs and GUIDs are unique. Ordinary duplicate/ambiguous forward prompts
  and repeated reverse prompts are refused; review context in both directions.
- Reference and dialogue kinds are explicit; an ordinary card cannot accidentally
  become a dialogue through a stray service tag. Cloze requires a real cloze marker.
- Dialogue structure, quiz sets, translations, original character alignment and
  complete phrase timing satisfy the new synchronized authoring profile.
- All declared media exist locally. CSS imports/fonts are included recursively;
  traversal and network-dependent assets are rejected. Source input is not executed.
- With audio checks, files actually decode and master duration agrees with metadata.
- Build reopens the real ZIP and SQLite and compares GUIDs/fields/media bytes.
  Existing release files are preserved. Builds do not call an LLM or ElevenLabs.

## What they do not establish

Evidence presence is not semantic entailment. A correct quote can be attached to
an incorrect interpretation. The agent must compare the authored content against
the sources, preserve exceptions, choose atomic prompts, verify translations and
check that quizzes follow from recordings. Percentage coverage refers to the
**agent’s explicit inventory**, not mathematically proven total source coverage.

OCR/ASR may be wrong; extracted text requires inspection where uncertain. A checked
file header or successful decoding is not proof that speech was understandable.
A provider alignment matching the transcript is not a substitute for listening.
Generated IPA is not a human-checked transcription of a particular speaker.

The HTML preview is for content inspection, not the mobile app's exact native UI.
Open the package in Anki/LingoDeck for actual rendering and interactions. Runtime
checkpoint playback progress is not a portable Anki scheduling field. Mobile
export limitations are documented in [the format specification](deck-format.md).

## First-version boundaries

- Content is authored by your existing agent; this repository is not a hosted
  website, GUI, background agent service or independent LLM provider integration.
- DOCX extraction groups paragraphs and tables; page 1 is a logical text document,
  not faithful Word pagination. PDF pages preserve physical page numbers.
- Source exclusions are currently per source, not per individual unread page.
- Unsupported formats need agent conversion/attached transcription or an explicit
  exclusion. There is no automatic browser crawl, video transcription or cloud OCR.
- Listening generation is currently ElevenLabs dialogue-with-timestamps; other
  providers can supply manually aligned ready episodes in the same open format.
- No phonetic generation tool is assumed installed. Pronunciation is optional data.
- No automatic public publishing. Building a deck and publishing a repository/deck
  are separate actions; source materials and credentials are not pushed by the CLI.

## Release report

`reports/qa.json` records concrete failures/warnings, number of notes/episodes/media,
inventory coverage, audio-decoding status and a hash of the current authoring inputs.
`reports/preaudio-qa.json` is a separate preflight, not a final release verdict.
`reports/release.json` references the actual package and reports Anki card count
(one reversed note creates two cards). `reports/preview.html` supports visual content
review. Report manual checks as performed/pending rather than fabricating a score.

## Regression suite

Run `uv run pytest` and `uv run ruff check .`. Tests cover mixed Anki models,
source grounding, changes/unread sources, identity preservation, container/media
integrity, arbitrary language pairs, real local decoding, script fingerprints,
provider error recovery, cache reuse and pre-request budget enforcement.
All network audio responses are mocked; the suite requires no account/API keys.
