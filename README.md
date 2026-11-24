# Szuper Forge

A local agent harness that turns a folder of teaching materials into a grounded,
reviewable **Anki `.apkg`**, including Szuper theory pages and optional
synchronized dialogue listening lessons.

Give your coding agent the materials folder and the desired languages/level.
The agent reads the sources and authors the content. Szuper Forge handles extraction,
source references, coverage checks, stable identities, audio and packaging.
**No separate LLM API key is required**: use the agent you already run.

Inspired by [etnamute](https://github.com/bes-dev/etnamute): short commands, shared
pipeline instructions, durable artifacts, explicit QA before delivery. This is an
independent implementation for learning materials, not an app builder.

[Project and support](https://bes-dev.com/szuper/) · [Deck creation guide](https://bes-dev.com/szuper/guide/) · [Privacy](https://bes-dev.com/szuper/privacy/) · [Terms](https://bes-dev.com/szuper/terms/)

## Start

Python 3.11+ and [uv](https://docs.astral.sh/uv/) or pip:

```sh
git clone https://github.com/bes-dev/szuper-forge.git
cd szuper-forge
./setup.sh
# or: uv sync --frozen && uv run --frozen szuper-forge doctor
```

Or `python3 -m venv .venv && .venv/bin/pip install -e .`.

The source checkout includes the agent skills and worked example. A wheel installs the CLI for scripted use.

Keep using the existing project folder when updating a deck.

Open this repository with Codex, Claude Code, or another file/terminal-capable
agent, and ask:

> Read AGENTS.md. Create an English→Russian A2 deck from `/path/to/materials`.
> Cover the supplied lessons, include theory and listening when configured.
> Save the project under `decks/english-a2` and finish with a validated .apkg.

Codex can invoke `$build-deck`; Claude Code can invoke `/build-deck`.
Both discover the same skills. Natural-language requests also work.
The agent asks only for missing choices that cannot be inferred (such as an
ambiguous language pair), then continues through the pipeline.

```text
materials → extract/OCR → grounded plan → cards + theory + listening scripts
          → optional ElevenLabs audio/timestamps → QA → preview + .apkg + report
```

For a lesson with a teacher, a sufficient brief is:

> Добавь сегодняшний конспект в мою колоду. В приоритете мои ошибки и фразы, которые я хотел сказать. Объедини повторы, сохрани историю и покажи изменения. Озвучка не нужна.

For a full course, specify the intended outcome and whether coverage must be exhaustive. The same workflow produces a sequenced contents list, self-contained chapters and linked practice. You can review the result offline in `reports/preview.html`. Original evidence stays in the authoring project (`reports/provenance.json`).

## What it supports

- PDF text extraction page by page; scanned PDF and image OCR with optional
  Tesseract/Poppler, or agent vision via `attach-text`.
- UTF-8 TXT/Markdown/CSV/TSV/JSON/HTML; DOCX paragraphs and tables.
- Audio files inventoried for transcription; use your agent/local ASR and attach
  the result. ASR is not silently replaced by guessed text.
- Unsupported/empty/failed sources remain visible and block release until read,
  converted, or explicitly excluded with a reason.
- Basic, Basic + reverse, Cloze, topic tags and HTML theory in the same package.
- Whole dialogue episodes with per-phrase original, translation, optional
  pronunciation, speaker, real timing and objective comprehension quizzes.
- Stable GUIDs independent of mutable titles, translations and tags.
- Local source evidence, inventory coverage, duplicate/ambiguity checks,
  media validation, actual ZIP/SQLite round-trip verification and HTML preview.
- Resumable audio with payload-hash caching, bounded characters and no automatic
  retries after an uncertain paid request.

A folder of sources does not mechanically imply one uniquely correct curriculum.
The agent performs the pedagogical work; the tools verify the declared plan and
evidence. “100% inventory coverage” means all authored inventory items are covered,
not that a model has proved it understood every concept in the materials.

## Try without any API keys

```sh
uv run python examples/create_demo.py /tmp/szuper-forge-demo
uv run szuper-forge qa /tmp/szuper-forge-demo
uv run szuper-forge build /tmp/szuper-forge-demo --output /tmp/szuper-forge-demo/dist/demo.apkg
```

The demo includes three reversible vocabulary notes, one Cloze, one theory page,
one factual Basic note and an optional listening script. Audio is disabled by
default; the report explicitly says it was omitted. No placeholder recordings
are shipped. Open `reports/preview.html`, then import `.apkg` into Anki/Szuper.

## Optional listening with ElevenLabs

Install `ffmpeg`/`ffprobe`. Export a key in the shell (never put it in project JSON):

```sh
export ELEVENLABS_API_KEY='your-key'
```

In `project.json`, set `audio.enabled: true`, a character budget, and a mapping
from **your script’s speaker names** to voice IDs available in your ElevenLabs
account. No voices or language pairs are hardcoded. For the demo, speaker names
are `Customer` and `Server`; choose their actual voice IDs in the config.

```sh
uv run szuper-forge audio /tmp/szuper-forge-demo           # offline plan, no paid requests
uv run szuper-forge audio /tmp/szuper-forge-demo --execute # generate within configured ceiling
uv run szuper-forge qa /tmp/szuper-forge-demo --check-audio
uv run szuper-forge build /tmp/szuper-forge-demo --output /tmp/szuper-forge-demo/dist/with-listening.apkg
```

The integration uses ElevenLabs’ documented
[dialogue-with-timestamps endpoint](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert-with-timestamps).
Each semantic segment is one multi-voice request, up to 2,000 input characters and
10 unique voices. Returned original character alignment must match the authored
transcript. Segments are decoded to common PCM and assembled into a WAV master;
phrase positions use real sample offsets. No estimated timing from text length.
WAV intentionally avoids introducing new encoder delays during concatenation.

The character ceiling is a workflow limit, **not a guaranteed currency price**.
Text-only planning costs nothing. The key alone does not send requests:
`audio.enabled` plus `--execute` is required. Your agent may execute within an
already authorized configuration; another confirmation is not a normal pipeline step.
After a transport error the outcome may be unknown: inspect provider history,
then explicitly reconcile if you want a possibly paid retry. See [audio runbook](docs/audio.md).

Source documents stay local to these CLI tools. Only authored dialogue text and
voice IDs are submitted by the ElevenLabs integration. Your agent’s handling of
source material follows its own model/provider configuration.

## Agent commands and artifacts

| Agent skill | Purpose |
|---|---|
| `build-deck` | Full source-to-deck workflow and incremental updates |
| `audit-materials` | Extraction, source inventory and grounded learning plan |
| `generate-listening` | Author and synthesize synchronized dialogue lessons |
| `verify-deck` | Structural/content QA, repair and final release |
| `deck-authoring` | Shared pedagogical and format guidance |

```text
decks/<name>/
  project.json                    # persistent IDs, languages, material path, audio budget/voices
  sources/manifest.json           # hashes, source IDs, page text, extraction status
  plan.json                       # objectives, exact source evidence, explicit exclusions
  deck.json                       # Basic/Reversed/Cloze/reference notes
  scripts.json                    # untimed authored dialogues and quizzes
  dialogues.json                  # generated/author-aligned runtime-ready episodes
  sources/listening-bindings.json # episode → source inventory, script fingerprint
  media/                          # included local media; generated master/segment WAVs
  .cache/elevenlabs/               # successful responses, reusable after local failures
  audio-ledger.json                # reserved/used characters, unresolved requests
  reports/                        # QA, audio plan, preview, release report
  dist/                           # final .apkg files
```

Generated projects/materials are ignored by this repository. They may contain
private teaching content. Releasing a `.apkg` does not automatically publish it
or upload the source folder to GitHub.

## Documentation

- [Agent operating instructions](AGENTS.md)
- [Pipeline and input schemas](docs/pipeline.md)
- [Full implemented Szuper deck specification](docs/deck-format.md)
- [Audio, caching and recovery](docs/audio.md)
- [Validation and limitations](docs/validation.md)
- [Example project generator](examples/create_demo.py)

The specification and dialogue parser/packager were seeded from the Szuper
format; [upstream hashes](docs/upstream.json) record the snapshot. No runtime
checkout of the mobile app is needed. Format updates should be synchronized with
both mobile parsers before changing the version contract.

## Development

```sh
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
```

Tests use local teaching fixtures and mocked provider responses. They exercise
real ffmpeg decoding when audio tests run; they never consume ElevenLabs credits.
CI runs on Linux and macOS. Optional OCR requires additional local binaries;
the `attach-text` workflow works without them.
