import base64
import io
import json
import wave

import httpx
import pytest

from szuper_forge.audio import generate, plan_audio, reconcile
from szuper_forge.common import ForgeError, read, write
from szuper_forge.dialogue import load_document
from szuper_forge.packaging import build
from szuper_forge.quality import run_qa


def enabled(demo, budget=10000):
    config = read(demo / "project.json")
    config["audio"].update(
        enabled=True, voices={"Customer": "voice-A", "Server": "voice-B"}, max_characters=budget
    )
    write(demo / "project.json", config)


def response_for(payload):
    data = io.BytesIO()
    with wave.open(data, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(44100)
        stream.writeframes(b"\0\0" * (44100 * 6))
    # Synthetic fixture: real WAV decoding, no claim to be real spoken audio.
    content = "".join(p["text"] for p in payload["inputs"])
    step = 5.0 / len(content)
    return {
        "audio_base64": base64.b64encode(data.getvalue()).decode(),
        "alignment": {
            "characters": list(content),
            "character_start_times_seconds": [i * step for i in range(len(content))],
            "character_end_times_seconds": [(i + 1) * step for i in range(len(content))],
        },
    }


def mock_client(calls, mutate=None):
    def handler(request):
        calls.append(request)
        data = response_for(json.loads(request.content))
        if mutate:
            mutate(data)
        return httpx.Response(200, json=data)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_plan_is_offline_and_generation_is_bounded_and_resumable(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "never-save-this-test-key")
    plan = plan_audio(demo)
    assert plan["new_requests"] == 1 and plan["new_characters"] > 0
    calls = []
    with mock_client(calls) as client:
        generated = generate(demo, execute=True, client=client)
        assert generated["episodes"] == 1 and len(calls) == 1
        monkeypatch.delenv("ELEVENLABS_API_KEY")
        generate(demo, execute=True, client=client)
        assert len(calls) == 1  # Successful cache reprocessing needs no key or new request.
    _, rows = load_document(demo / "dialogues.json")
    assert rows[0][0]["segments"][0]["phrases"][1]["start"] > 0
    assert run_qa(demo, check_audio=True)["passed"]
    result = build(demo, demo / "dist/listening.apkg")
    assert result["notes"] == 7 and result["anki_cards"] == 10
    for path in demo.rglob("*.json"):
        assert "never-save-this-test-key" not in path.read_text()


def test_budget_rejected_before_sending_any_request(demo, monkeypatch):
    enabled(demo, budget=1)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret")
    calls = []
    with mock_client(calls) as client:
        with pytest.raises(ForgeError, match="budget exceeded"):
            generate(demo, execute=True, client=client)
    assert calls == []


def test_key_missing_does_not_send_request_or_reserve_credits(demo, monkeypatch):
    enabled(demo)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    calls = []
    with mock_client(calls) as client:
        with pytest.raises(ForgeError, match="not set"):
            generate(demo, execute=True, client=client)
    assert not calls and not (demo / "audio-ledger.json").exists()


def test_transport_failure_never_automatically_retries_or_leaks_key(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-private-key")
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("test-private-key")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="outcome is unknown") as failure:
            generate(demo, execute=True, client=client)
        assert "test-private-key" not in str(failure.value)
        with pytest.raises(ForgeError, match="Unresolved paid"):
            generate(demo, execute=True, client=client)
    assert len(calls) == 1
    ledger = read(demo / "audio-ledger.json")
    with pytest.raises(ForgeError, match="Explicit"):
        reconcile(demo, ledger["attempts"][0]["key"], False)
    reconcile(demo, ledger["attempts"][0]["key"], True)
    assert plan_audio(demo)["reserved_or_used_characters"] > 0


def test_mismatched_alignment_keeps_successful_response_and_never_regenerates(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret")
    calls = []

    def corrupt(data):
        data["alignment"]["characters"][0] = "X"

    with mock_client(calls, corrupt) as client:
        for _ in range(2):
            with pytest.raises(ForgeError, match="differs from authored"):
                generate(demo, execute=True, client=client)
    assert len(calls) == 1
    assert not (demo / "dialogues.json").exists()


def test_scripts_changed_after_generation_cannot_build_stale_audio(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret")
    calls = []
    with mock_client(calls) as client:
        generate(demo, execute=True, client=client)
        scripts = read(demo / "scripts.json")
        scripts["episodes"][0]["segments"][0]["phrases"][0]["translation"] = "Мне чай, пожалуйста."
        write(demo / "scripts.json", scripts)
        assert "scripts changed" in run_qa(demo)["errors"][0]
        generate(demo, execute=True, client=client)
    assert len(calls) == 1  # Translation changes do not require paid TTS regeneration.
    assert run_qa(demo)["passed"]


def test_arbitrary_language_pair_comes_from_data(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret")
    scripts = read(demo / "scripts.json")
    episode = scripts["episodes"][0]
    episode.update(language="ja", translation_language="es")
    phrases = episode["segments"][0]["phrases"]
    phrases[0].update(text="お茶をください。", translation="Té, por favor.")
    phrases[1].update(text="ミルクはいかがですか。", translation="¿Con leche?")
    write(demo / "scripts.json", scripts)
    calls = []
    with mock_client(calls) as client:
        generate(demo, execute=True, client=client)
    payload = json.loads(calls[0].content)
    assert payload["language_code"] == "ja"
    _, rows = load_document(demo / "dialogues.json")
    assert rows[0][0]["translation_language"] == "es"
    assert rows[0][0]["segments"][0]["phrases"][0]["text"] == "お茶をください。"


def test_invalid_quiz_or_unread_source_prevents_paid_calls(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret")
    scripts = read(demo / "scripts.json")
    scripts["episodes"][0]["segments"][0]["question"]["options"][1]["correct"] = True
    write(demo / "scripts.json", scripts)
    calls = []
    with mock_client(calls) as client:
        with pytest.raises(ForgeError, match="correct and incorrect"):
            generate(demo, execute=True, client=client)
    assert not calls


def test_too_long_provider_segment_is_rejected_before_network(demo):
    enabled(demo)
    scripts = read(demo / "scripts.json")
    scripts["episodes"][0]["segments"][0]["phrases"][0]["text"] = "A" * 2001
    write(demo / "scripts.json", scripts)
    with pytest.raises(ForgeError, match="split into smaller"):
        plan_audio(demo)


def test_changed_voice_config_cannot_build_old_recording(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-secret")
    with mock_client([]) as client:
        generate(demo, execute=True, client=client)
    config = read(demo / "project.json")
    config["audio"]["voices"]["Customer"] = "different-voice"
    write(demo / "project.json", config)
    assert "Speech config changed" in run_qa(demo)["errors"][0]


def test_no_scripts_is_an_explicit_error(demo):
    write(demo / "scripts.json", {"episodes": []})
    with pytest.raises(ForgeError, match="No listening scripts"):
        plan_audio(demo)


def test_word_glosses_reuse_exact_synthesis_request(demo):
    from szuper_forge.audio import requests_for
    from szuper_forge.common import project
    from szuper_forge.models import Scripts, WordGloss

    enabled(demo)
    config = project(demo)
    scripts = Scripts.model_validate(read(demo / "scripts.json"))
    before = requests_for(config, scripts)
    phrase = scripts.episodes[0].segments[0].phrases[0]
    end = len(phrase.text.split()[0].rstrip(".,!?"))
    phrase.words = [WordGloss(start=0, end=end, translation="A contextual gloss")]
    assert requests_for(config, scripts) == before


def test_lost_paid_cache_requires_explicit_retry(demo, monkeypatch):
    enabled(demo)
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test-key")
    calls = []
    with mock_client(calls) as client:
        generate(demo, execute=True, client=client)
        (cached,) = (demo / ".cache/elevenlabs").glob("*.json")
        cached.unlink()
        assert plan_audio(demo)["unresolved_requests"] == [cached.stem]
        with pytest.raises(ForgeError, match="Unresolved paid"):
            generate(demo, execute=True, client=client)
        assert len(calls) == 1
        reconcile(demo, cached.stem, True)
        generate(demo, execute=True, client=client)
        assert len(calls) == 2
