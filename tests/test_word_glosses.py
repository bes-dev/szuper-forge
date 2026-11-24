import xml.etree.ElementTree as ET

import pytest
from pydantic import ValidationError

from deck_forge.dialogue import Invalid, phrase_markup, word_glosses
from deck_forge.models import Phrase


def test_authored_unicode_glosses_do_not_change_audio_text():
    phrase = {"speaker": "A", "text": "👋 猫、猫!", "translation": "Hola", "words": [
        {"start": 2, "end": 3, "translation": "gato"},
        {"start": 4, "end": 5, "translation": "otro gato", "lemma": "猫"},
    ]}
    assert Phrase.model_validate(phrase).text == phrase["text"]
    node = ET.Element("div")
    phrase_markup(node, {"data-start": "3.548"}, phrase)
    paragraph = node[0]
    assert "".join(paragraph.itertext()) == phrase["text"]
    assert paragraph.get("data-start") == "3.548"
    assert [s.get("data-gloss") for s in paragraph] == ["gato", "otro gato"]


@pytest.mark.parametrize("words", [
    [{"start": -1, "end": 1, "translation": "x"}],
    [{"start": 0, "end": 999, "translation": "x"}],
    [{"start": True, "end": 1, "translation": "x"}],
    [{"start": 0, "end": 1, "translation": ""}],
    [{"start": 0, "end": 2, "translation": "x"}, {"start": 1, "end": 2, "translation": "y"}],
])
def test_invalid_glosses_fail_before_packaging(words):
    phrase = {"speaker": "A", "text": "hello", "translation": "hola", "words": words}
    with pytest.raises(Invalid):
        word_glosses(phrase)
    with pytest.raises(ValidationError):
        Phrase.model_validate(phrase)


def test_legacy_script_fingerprints_do_not_gain_empty_words():
    phrase = Phrase(speaker="A", text="猫", translation="gato")
    assert "words" not in phrase.model_dump(mode="json")
