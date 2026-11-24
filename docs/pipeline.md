# Source-to-deck pipeline

The harness is agent-driven. It does not run an invisible LLM in a Python loop:
your agent reads the source artifacts and writes the pedagogical artifacts.
Commands are deterministic tools around that work. All paths below are local.

## 1. Initialize or resume

```sh
uv run deck-forge init decks/my-course --materials '/path/to/materials' \
  --name 'My course' --source-language de --translation-language pl --level A2
uv run deck-forge extract decks/my-course
uv run deck-forge status decks/my-course
```

Project directory must be outside the input folder. Existing projects are resumed,
not reinitialized. `project.json` contains persistent uid/deck/model IDs, languages,
level and audio settings. The source and translation pair above is an example,
not a default. Root materials path is absolute in local config; local evidence uses relative filenames and pages.

All machine-readable artifact contracts are in [`../schemas/`](../schemas/).
Regenerate after changing models:

```sh
uv run deck-forge schemas --output schemas
```

## 2. Read source inventory

`extract` recursively inventories non-hidden regular files, excludes symlinks,
checks a 2,000-file / 100 MiB-per-file ceiling and stores source hashes/page text.
Unsupported formats are recorded as unread, not silently ignored. Hidden files
(including `.env`), symlinks and hidden directories are deliberately not ingested.

`source_id` is `src-` plus the first 16 hex characters of SHA256 of the relative
POSIX filename. It stays stable when file content changes; a source content hash
must match the actual input before release. Unchanged files preserve attached
vision/transcription output. Changed files are re-extracted and old evidence must
be rechecked. Renaming a file changes its source ID.

```sh
uv run deck-forge source decks/my-course src-ID --page 3 --offset 0 --limit 12000
```

No PDF page text: `needs-ocr`; image: `needs-vision`; audio: `needs-transcription`.
Use OCR if installed:

```sh
# Supply installed Tesseract language packs, not arbitrary BCP-47 codes.
uv run deck-forge extract decks/my-course --ocr-language deu+eng
```

Scanned PDF OCR needs `pdftoppm` (Poppler) and Tesseract. Otherwise have the agent
inspect the original image/PDF with its own capabilities and write faithful text:

```sh
uv run deck-forge attach-text decks/my-course --source-id src-ID --page 3 \
  --text /path/to/transcribed-page.txt --method agent-vision
```

Methods: `agent-vision`, `manual-transcript`, `local-asr`. Methods describe origin,
not human verification. Check source language spelling/diacritics and tables before
using OCR as evidence. A failed extractor retains its error class and can be
retried after fixing the source/tool; no text is invented.

## 3. Author a grounded inventory

Write `plan.json` with all meaningful objectives from the material:

```json
{
  "items": [{
    "id": "polite-request",
    "topic": "Everyday::Cafe",
    "objective": "Make a polite request",
    "refs": [{"source_id": "src-ID", "page": 1, "quote": "Use please to make a request polite."}]
  }],
  "excluded_items": [],
  "excluded_sources": []
}
```

The quote must actually occur on the page (comparison normalizes Unicode and
whitespace, not words). Every inventory item needs evidence. Every inventoried
source must be referenced or explicitly excluded with `{"id": "src-ID", "reason":
"specific reason"}`. Unread pages block release unless the source is explicitly
excluded. To use some pages of a partly scanned source, resolve its other pages
first; this first version supports source-level, not page-level exclusions.

Use `excluded_items` for a deliberate scope decision with the objective ID/reason.
It remains visible in the coverage report and lowers the coverage fraction. It
cannot also be covered by an emitted note. Do not turn a fixable error into an
exclusion to get a green report.

## 4. Author cards and theory

`deck.json` is a `notes` array:

```json
{
  "notes": [{
    "id": "tea-vocab",
    "kind": "reversed",
    "front": "tea",
    "back": "чай",
    "tags": ["Everyday::Cafe"],
    "source_item_ids": ["tea-word"]
  }]
}
```

Fields: `id`, `kind`, `front`, `back`, `source_item_ids` required. Optional `tags`,
`hint`, `extra`, `examples`, `provenance`, explicit legacy `guid`. Allowed kinds:

| Kind | Anki output |
|---|---|
| basic | One forward card |
| reversed | Forward + reversed cards sharing a note GUID |
| cloze | Canonical Cloze in Front, e.g. `Tea, {{c1::please}}.`; Back is explanation |
| reference | One Basic note with reference/theory tags; Back is HTML chapter |

A note may cover several inventory items, but must remain pedagogically focused.
The builder records evidence and author provenance by GUID in local `reports/provenance.json`. Packaged Source fields are empty; keep any required public credits in a designated credit notice.
Do not copy Source into Hint. Media references are ordinary Anki sound/HTML
references; put files in `media/`, with safe flat names. Local CSS imports/fonts
are collected recursively. Remote files are not fetched. Mobile layouts should
be flexible, support light/dark themes and avoid JS/iframe dependencies.

Basic GUID = first 20 hex characters of SHA256 of `project.uid + ":" + note.id`,
unless explicit `guid` is supplied. Never change uid/note ID just to rename a
card. Models use `model_id` (basic/reference), `+1` (reversed), `+2` (Cloze), `+3`
(dialogue). Package filenames do not participate in identity.

## 5. Author optional listening

Write `scripts.json`, or leave `{"episodes": []}` if listening is not requested.
Each episode uses the [Scripts schema](../schemas/scripts.schema.json):

- Stable id, title/intro, source and translation languages, source provenance,
  topic tags, `source_item_ids`, optional legacy guid and Anki reveal labels.
- 1–32 segments: stable id, phrases, one quiz.
- Phrase: speaker, text, translation, optional pronunciation/system; **no guessed times**.
- Quiz: type, prompt, 2–8 uniquely identified options with correct booleans,
  explanation. `choice`/`true-false` have one correct, `select` uses an exact set.

See [the runnable demo](../examples/create_demo.py) for all artifact shapes.
[Audio runbook](audio.md) explains generation, cache and existing recordings.

## 6. Validate and package

```sh
uv run deck-forge qa decks/my-course --check-audio
uv run deck-forge build decks/my-course --output decks/my-course/dist/v1.apkg
```

Build always re-runs QA and audio decoding for generated listening. No API calls
occur during QA/build. Output is staged; actual ZIP/SQLite/media and note fields
are reopened and compared before the final package appears. Existing release
files are not overwritten: use a new filename while retaining semantic IDs.

Outputs: `.apkg`, `reports/qa.json`, `reports/release.json`, `reports/preview.html`.
Inspect content and import into available Anki/LingoDeck. Device playback and
human listening review are separate checks; report them honestly.

All mutating CLI stages use `.forge.lock` to avoid concurrent project writers.
After an interrupted process, inspect the PID/process state before removing a
stale lock. Never erase audio cache/ledger to force regeneration.

## Updates

Keep the project and authoring artifacts. Re-extract changed sources, review
invalidated evidence, edit affected notes/scripts and regenerate only matching
changed audio payloads. Changing only translation or quiz can reuse speech cache.
Source hashes and script fingerprints prevent passing a stale release report.
Build refuses stale listening bindings when scripts have changed. Phrase IDs in
runtime v1 are positional; inserting/reordering affects an unfinished checkpoint.
