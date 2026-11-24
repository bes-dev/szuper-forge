from __future__ import annotations
import base64
import math
from pathlib import Path
import os
import shutil
import subprocess
import unicodedata
import wave

import httpx

from .common import check, digest, project, read, write
from .dialogue import validate_html, markup, verify_media
from .models import Scripts
from .quality import run_qa, validate_scripts

ENDPOINT = "https://api.elevenlabs.io/v1/text-to-dialogue/with-timestamps"
SAMPLE_RATE = 44100


def requests_for(config, scripts):
    validate_scripts(config, scripts)
    result = []
    for episode in scripts.episodes:
        for segment in episode.segments:
            inputs = []
            for phrase in segment.phrases:
                voice = config.audio.voices.get(phrase.speaker)
                check(voice, f"Configure audio.voices for speaker: {phrase.speaker}")
                inputs.append({"text": phrase.text, "voice_id": voice})
            check(
                len({i["voice_id"] for i in inputs}) <= 10,
                "ElevenLabs supports at most 10 unique voices per request",
            )
            characters = sum(len(i["text"]) for i in inputs)
            check(
                characters <= config.audio.max_request_characters,
                f"{episode.id}/{segment.id}: split into smaller semantic segments (max {config.audio.max_request_characters} characters)",
            )
            payload = {"inputs": inputs, "model_id": config.audio.model}
            language = episode.language.split("-")[0]
            if len(language) == 2:
                payload["language_code"] = language
            key = digest({"endpoint": ENDPOINT, "output_format": "mp3_44100_128", "payload": payload})
            result.append(
                {
                    "episode_id": episode.id,
                    "segment_id": segment.id,
                    "characters": characters,
                    "key": key,
                    "payload": payload,
                }
            )
    return result


def plan_audio(root):
    root = Path(root)
    config = project(root)
    scripts = Scripts.model_validate(read(root / "scripts.json"))
    check(bool(scripts.episodes), "No listening scripts authored yet")
    reqs = requests_for(config, scripts)
    ledger = read(root / "audio-ledger.json") if (root / "audio-ledger.json").exists() else {"attempts": []}
    spent = sum(a["characters"] for a in ledger["attempts"])
    cache = root / ".cache/elevenlabs"
    unique = {r["key"]: r for r in reqs}
    uncached = [r for r in unique.values() if not (cache / (r["key"] + ".json")).exists()]
    unresolved = [
        a["key"]
        for a in ledger["attempts"]
        if a["state"] in {"started", "complete"} and a["key"] in {r["key"] for r in uncached}
    ]
    result = {
        "provider": "ElevenLabs",
        "endpoint": ENDPOINT,
        "enabled": config.audio.enabled,
        "segments": len(reqs),
        "unique_requests": len(unique),
        "cached_requests": len(unique) - len(uncached),
        "new_requests": len(uncached),
        "new_characters": sum(r["characters"] for r in uncached),
        "reserved_or_used_characters": spent,
        "character_budget": config.audio.max_characters,
        "unresolved_requests": unresolved,
        "cost_note": "Character ceiling is not a price quote; provider credits/pricing depend on the account/model.",
    }
    write(root / "reports/audio-plan.json", result)
    return result


def canonical_characters(alignment):
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])
    check(chars and len(chars) == len(starts) == len(ends), "Missing/malformed original character alignment")
    result = []
    for raw, start, end in zip(chars, starts, ends):
        check(
            isinstance(raw, str)
            and type(start) in (int, float)
            and type(end) in (int, float)
            and math.isfinite(start)
            and math.isfinite(end)
            and 0 <= start <= end,
            "Invalid aligned character timing",
        )
        for char in unicodedata.normalize("NFD", raw):
            if not char.isspace():
                result.append((char, start, end))
    return result


def aligned_ranges(segment, response, duration):
    # Use original-text alignment. Normalized text may spell numbers differently.
    aligned = canonical_characters(response.get("alignment") or {})
    expected = [
        "".join(c for c in unicodedata.normalize("NFD", p.text) if not c.isspace()) for p in segment.phrases
    ]
    check(
        "".join(c for c, _, _ in aligned) == "".join(expected),
        "Alignment differs from authored transcript; cached audio retained, no guessing or automatic regeneration",
    )
    ranges = []
    cursor = 0
    previous = -1.0
    for phrase in expected:
        check(phrase, "Empty spoken phrase")
        part = aligned[cursor : cursor + len(phrase)]
        cursor += len(phrase)
        start = min(t[1] for t in part)
        end = max(t[2] for t in part)
        check(
            start >= previous and end > start and end <= duration + 0.05,
            "Invalid/overlapping phrase alignment; review cached recording",
        )
        end = min(end, duration)
        ranges.append((start, end))
        previous = end
    return ranges


def decode(mp3, wav):
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-xerror",
            "-y",
            "-i",
            str(mp3),
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            "1",
            "-c:a",
            "pcm_s16le",
            str(wav),
        ],
        check=True,
        capture_output=True,
    )
    with wave.open(str(wav), "rb") as stream:
        check(stream.getnframes() > 0, "Provider returned empty audio")
        return stream.readframes(stream.getnframes())


def fetch_response(root, req, key, client):
    cache = root / ".cache/elevenlabs"
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / (req["key"] + ".json")
    if target.exists():
        return read(target)
    ledger_path = root / "audio-ledger.json"
    ledger = read(ledger_path) if ledger_path.exists() else {"attempts": []}
    check(
        not any(a["key"] == req["key"] and a["state"] in {"started", "complete"} for a in ledger["attempts"]),
        "Unresolved paid request; inspect provider history and use audio-reconcile before an intentional retry",
    )
    check(key, "ELEVENLABS_API_KEY is not set. No audio request was sent.")
    config = project(root)
    check(
        sum(a["characters"] for a in ledger["attempts"]) + req["characters"] <= config.audio.max_characters,
        "Project audio character budget exceeded",
    )
    attempt = {"key": req["key"], "characters": req["characters"], "state": "started"}
    ledger["attempts"].append(attempt)
    write(ledger_path, ledger)
    try:
        response = client.post(
            ENDPOINT,
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": key},
            json=req["payload"],
        )
        check(
            response.status_code == 200,
            f"ElevenLabs HTTP {response.status_code}. Request left unresolved; no automatic paid retry.",
        )
        data = response.json()
        check(
            isinstance(data, dict) and isinstance(data.get("audio_base64"), str),
            "Invalid provider response; request left unresolved, no automatic paid retry",
        )
        audio = base64.b64decode(data["audio_base64"], validate=True)
        check(bool(audio), "ElevenLabs returned no audio")
        # Persist successful output before processing so local failures never trigger a second paid call.
        write(target, data)
        attempt["state"] = "complete"
        write(ledger_path, ledger)
        return data
    except httpx.HTTPError as exc:
        # Never stringify transport URLs/headers/body (they may include credentials).
        raise ValueError(
            "ElevenLabs transport failed; request outcome is unknown. Cached results retained, no automatic retry."
        ) from exc


def generate(root, execute=False, client=None):
    root = Path(root)
    config = project(root)
    plan = plan_audio(root)
    if not execute:
        return plan
    check(config.audio.enabled, "Enable audio in project.json to generate listening")
    check(
        not plan["unresolved_requests"],
        "Unresolved paid requests; inspect audio-ledger.json and provider history",
    )
    check(
        plan["reserved_or_used_characters"] + plan["new_characters"] <= plan["character_budget"],
        "Project character budget exceeded before any API request",
    )
    check(shutil.which("ffmpeg") and shutil.which("ffprobe"), "Install ffmpeg (including ffprobe)")
    preflight = run_qa(root, preparing_audio=True)
    check(preflight["passed"], "Source/content preflight failed: " + "; ".join(preflight["errors"]))
    scripts = Scripts.model_validate(read(root / "scripts.json"))
    reqs = {(r["episode_id"], r["segment_id"]): r for r in requests_for(config, scripts)}
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    own_client = client is None
    client = client or httpx.Client(timeout=120, follow_redirects=False)
    media = root / "media"
    media.mkdir(exist_ok=True)
    cache = root / ".cache/elevenlabs"
    cache.mkdir(parents=True, exist_ok=True)
    episodes = []
    try:
        for script in scripts.episodes:
            episode = script.model_dump(mode="json", exclude_none=True)
            episode.pop("source_item_ids")
            episode["segments"] = []
            episode["source"] += (
                f"; ElevenLabs {config.audio.model}, provider character timestamps; listening review not automatically asserted"
            )
            frames = bytearray()
            for segment in script.segments:
                req = reqs[(script.id, segment.id)]
                data = fetch_response(root, req, key, client)
                mp3 = cache / (req["key"] + ".mp3")
                mp3.write_bytes(base64.b64decode(data["audio_base64"], validate=True))
                wav = media / ("segment-" + req["key"][:20] + ".wav")
                pcm = decode(mp3, wav)
                duration = len(pcm) / (2 * SAMPLE_RATE)
                offset = len(frames) / (2 * SAMPLE_RATE)
                ranges = aligned_ranges(segment, data, duration)
                ready = {
                    "id": segment.id,
                    "audio": wav.name,
                    "phrases": [],
                    "question": segment.question.model_dump(),
                }
                for phrase, (start, end) in zip(segment.phrases, ranges):
                    item = phrase.model_dump(exclude_none=True)
                    item.update(start=round(offset + start, 6), end=round(offset + end, 6))
                    ready["phrases"].append(item)
                ready["translation"] = "\n".join(p.translation for p in segment.phrases)
                episode["segments"].append(ready)
                frames.extend(pcm)
            master = media / ("master-" + digest(bytes(frames))[:20] + ".wav")
            with wave.open(str(master), "wb") as stream:
                stream.setnchannels(1)
                stream.setsampwidth(2)
                stream.setframerate(SAMPLE_RATE)
                stream.writeframes(frames)
            episode.update(audio=master.name, duration=len(frames) / (2 * SAMPLE_RATE))
            if episode.get("guid") is None:
                episode.pop("guid", None)
            validate_html(markup(episode))
            episodes.append(episode)
        doc = {
            "deck": {"id": config.deck_id, "name": config.name, "model_id": config.model_id + 3},
            "episodes": episodes,
        }
        all_media = set().union(*(validate_html(markup(e)) for e in episodes))
        verify_media(media, all_media, episodes, True)
        write(root / "dialogues.json", doc)
        write(
            root / "sources/listening-bindings.json",
            {
                "scripts_sha256": digest(scripts.model_dump(mode="json")),
                "speech_config_sha256": digest({"model": config.audio.model, "voices": config.audio.voices}),
                "episodes": {e.id: {"source_item_ids": e.source_item_ids} for e in scripts.episodes},
            },
        )
        return {
            "episodes": len(episodes),
            "media_files": len(all_media),
            "audio": plan,
            "output": str(root / "dialogues.json"),
        }
    finally:
        if own_client:
            client.close()


def reconcile(root, request_key, allow_paid_retry):
    check(
        allow_paid_retry, "Explicit --allow-paid-retry required; previous attempt may have consumed credits"
    )
    path = Path(root) / "audio-ledger.json"
    ledger = read(path)
    matched = False
    for attempt in ledger["attempts"]:
        if attempt["key"] == request_key and (
            attempt["state"] == "started"
            or (
                attempt["state"] == "complete"
                and not (Path(root) / ".cache/elevenlabs" / (request_key + ".json")).is_file()
            )
        ):
            attempt["state"] = "retry-authorized"
            matched = True
    check(matched, "No unresolved request with this hash")
    # Reserved characters remain charged against our ceiling even when the account outcome is unknown.
    write(path, ledger)
    return {"request": request_key, "retry_authorized": True, "prior_reservation_retained": True}
