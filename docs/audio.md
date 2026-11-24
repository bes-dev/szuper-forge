# ElevenLabs audio runbook

## Configuration and authorized execution

Set `ELEVENLABS_API_KEY` in the environment; no automatic `.env` loader is used.
Never store it in project.json, a voice map, Source, scripts or the repository.
A key is not read from shell history or another project. `doctor` reports only
whether it exists, not its value.

```json
"audio": {
  "enabled": true,
  "model": "eleven_v3",
  "voices": {"Customer": "YOUR_VOICE_ID_A", "Server": "YOUR_VOICE_ID_B"},
  "max_characters": 10000,
  "max_request_characters": 2000
}
```

Voice keys must match actual script speakers, in any language. Use voices available
in your ElevenLabs account. The harness does not choose a default Hungarian,
Russian or English voice. It submits the source BCP-47 primary language as the
provider ISO-639-1 hint when it is two letters; it preserves the full authored
language code in the final note. Language/model support still depends on provider.

`szuper-forge audio PROJECT` is always an offline plan. `--execute` and enabled
configuration trigger requests only within the declared cumulative character
ceiling. A project initialized with audio disabled makes no requests.
The agent can proceed when the user's generation request, voices and budget are
already clear; it does not need repeated approvals of normal local steps.

## API contract

Verified against official documentation on 2026-11-17:

- [Create dialogue with timestamps](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert-with-timestamps)
- [Create dialogue](https://elevenlabs.io/docs/api-reference/text-to-dialogue/convert)
- [Forced alignment](https://elevenlabs.io/docs/api-reference/forced-alignment/create), available for manual/imported recording workflows; this harness does not call it automatically.

Used endpoint: `POST https://api.elevenlabs.io/v1/text-to-dialogue/with-timestamps`,
header `xi-api-key`, JSON `inputs` pairs of text/voice_id, `model_id`, optional
language_code; requested output `mp3_44100_128`. One semantic segment is one
request, ≤2,000 characters, ≤10 distinct voices. Returned audio_base64 and original
character alignment are required by this integration.

The original character sequence must match all authored phrases, after Unicode
canonical decomposition and whitespace removal. If the provider returns only
normalized text, omits text or changes it, alignment fails visibly. Nothing is
estimated from character counts, speaking rate or sentence count. Confidence of
what was actually spoken still requires listening; timestamp metadata alone does
not prove the recording faithfully contains all text.

The provider’s successful response is cached before decoding/alignment. Segment
MP3 is decoded to mono 44.1 kHz 16-bit PCM. Segment WAVs plus one concatenated WAV
master are packaged. Global phrase offsets use exact decoded sample counts;
per-phrase audio files are unnecessary. WAV is larger than MP3 but avoids a second
encoding-delay problem during assembly. All segment files remain present because
runtime v1 requires them even with a master.

## Cache and budget

Cache key hashes endpoint, output format and the full speech payload (model,
voices, text and language hint). A successful cached payload is never requested
again, even if a later local operation failed. Changing only translations or quiz
reuses audio; generated bindings also fingerprint the selected voice/model configuration,
so a changed speech configuration must be regenerated before release. Changing text/voice/model/language creates a different payload.

`audio-ledger.json` reserves characters **before** each uncached request. Successful
requests become `complete`; a timeout, error or crash may remain `started`.
A reservation counts against the project ceiling even if the remote outcome is
unknown. Duplicate payloads within the project share cached output. This bounds
requested text, not exact provider credits/currency. Pricing, voice eligibility,
quota and model behavior come from your account, not an invented local price.

No network call is made when total uncached text would exceed the ceiling. No
provider request is made before source/content preflight. Credentials are not
written to requests, payload hashes, ledgers or cached response metadata.

## Uncertain failure recovery

1. Preserve cache, ledger and existing media. Do not delete them to bypass a gate.
2. Check the request hash and provider history/account outcome. A local timeout
   does not establish that the provider did not charge or generate audio.
3. If a usable provider response can be recovered, cache it under the original
   request hash; inspect the expected response shape first.
4. If the user explicitly authorizes a possible paid retry, use:

```sh
szuper-forge audio-reconcile PROJECT --request HASH --allow-paid-retry
szuper-forge audio PROJECT --execute
```

The old reservation remains counted; increase the project ceiling only if the
user’s authorized budget permits it. The agent must not perform reconciliation
as an automatic response to every network error. The normal cached resume needs
no key when every required response is already present.

## Existing recordings

No TTS is required for authored recordings. Prepare real master/segment media and
`dialogues.json` in [the format specification](deck-format.md). Its deck id must
match project.deck_id, model_id must be project.model_id + 3. Use stable explicit
legacy GUIDs when migrating existing published episodes.

Provide `sources/listening-bindings.json`:

```json
{"episodes": {"episode-id": {"source_item_ids": ["objective-id"]}}}
```

If `scripts.json` also contains episodes, bindings must additionally contain
`scripts_sha256`, computed using `szuper_forge.common.digest` of
`Scripts.model_validate(...).model_dump(mode="json")`. This prevents stale script
updates from silently reusing old authored media. When adopting an external ready
format without an untimed source script, leave scripts episodes empty.
Use manual alignment, provider-returned timestamps or an authorized forced-aligner;
never fabricate boundaries. `qa --check-audio` validates decoding/durations; human
listening checks transcript quality and speech boundaries.

## Tests

Harness tests use `httpx.MockTransport` and temporary WAV fixtures. Those fixtures
contain synthetic silence solely to test decoding/alignment plumbing; they are
not examples of spoken lessons and are never released to users. The real endpoint
is never contacted by the test suite. Real provider synthesis has not been claimed
unless explicitly run and reviewed for the user’s actual project.

## Verified timestamp-provider limitation

During the 100-episode Hungarian collection audit, returned character/voice-segment
timestamps were cumulatively early relative to the actual audio. Matching the
character sequence and finite bounds did not establish synchronization accuracy.
The final spoken span could be0.56–11.36seconds longer than the metadata, with
phrase starts corrected by up to13.227seconds after independent word alignment.
Do not publish raw provider timestamps as acoustically verified. Check the final
master with independent word/forced alignment and acoustic speech/silence bounds;
never apply a speculative universal offset or text-length rescaling. Existing
audio can be reused. Recut derived section clips at measured silent boundaries
when retiming; updating HTML alone would leave classic Anki segment playback stale.
A saved exercise checkpoint must hydrate the current imported card and recompute
its cue from valid audio seconds only when the episode HTML changed, retaining
answers/help evidence.


## Optional offline word translations

`phrases[].words` contains `{start,end,translation,lemma?}` with Python/Unicode
code-point ranges in the unchanged phrase text. The packager emits direct
`span[data-gloss]` children. These are word-form meanings in the sentence, not
queries to a live translation API. Updating glosses preserves request text and
cached audio; no new synthesis is needed. Keep all audio timestamps and identities.
See dialogue format §5.3.1; native ranges are derived from HTML, not serialized
Python indices. Both mobile apps underline clickable words with a dashed line,
pause for lookup and show a small anchored bubble. Whole-phrase meaning remains
separate, and word help is included in the lesson assistance state.

If a previously paid response disappears from the cache, the next run reports its request hash as unresolved. Restore the cached response from backup or deliberately authorize another paid attempt with `audio-reconcile` after checking provider history. The earlier character reservation still counts.
