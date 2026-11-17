from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)


class AudioConfig(Model):
    enabled: bool = False
    model: str = "eleven_v3"
    voices: dict[str, str] = Field(default_factory=dict)
    max_characters: int = Field(default=10000, ge=1)
    max_request_characters: int = Field(default=2000, ge=1, le=2000)


class Project(Model):
    version: Literal[1] = 1
    uid: str
    name: str = Field(min_length=1)
    materials: str
    source_language: str = Field(min_length=2)
    translation_language: str = Field(min_length=2)
    level: str = "unspecified"
    deck_id: int = Field(gt=0, lt=2**53)
    model_id: int = Field(gt=0, lt=2**53 - 10)
    audio: AudioConfig = Field(default_factory=AudioConfig)


class Ref(Model):
    source_id: str
    page: int | None = Field(default=None, ge=1)
    quote: str = Field(min_length=1)


class PlanItem(Model):
    id: str = Field(min_length=1)
    topic: str = Field(min_length=1)
    objective: str = Field(min_length=1)
    refs: list[Ref] = Field(min_length=1)


class Exclusion(Model):
    id: str
    reason: str = Field(min_length=1)


class Plan(Model):
    items: list[PlanItem] = Field(min_length=1)
    excluded_items: list[Exclusion] = Field(default_factory=list)
    excluded_sources: list[Exclusion] = Field(default_factory=list)


class Note(Model):
    id: str = Field(min_length=1)
    kind: Literal["basic", "reversed", "cloze", "reference"]
    front: str = Field(min_length=1)
    back: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    hint: str = ""
    extra: str = ""
    examples: str = ""
    provenance: str = ""
    guid: str | None = None
    source_item_ids: list[str] = Field(min_length=1)

    @field_validator("tags")
    @classmethod
    def tags_are_tokens(cls, tags):
        if any(not t or any(c.isspace() for c in t) for t in tags):
            raise ValueError("Tags must be nonempty Anki tokens without whitespace")
        return tags


class DeckDraft(Model):
    notes: list[Note] = Field(default_factory=list)


class Option(Model):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    correct: bool


class Question(Model):
    type: Literal["choice", "true-false", "select"]
    prompt: str = Field(min_length=1)
    options: list[Option] = Field(min_length=2, max_length=8)
    explanation: str = Field(min_length=1)


class Phrase(Model):
    speaker: str = Field(min_length=1)
    text: str = Field(min_length=1)
    translation: str = Field(min_length=1)
    pronunciation: str | None = None
    pronunciation_system: str | None = None


class Segment(Model):
    id: str = Field(min_length=1)
    phrases: list[Phrase] = Field(min_length=1)
    question: Question


class Script(Model):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    intro: str = Field(min_length=1)
    language: str = Field(min_length=2)
    translation_language: str = Field(min_length=2)
    tags: list[str] = Field(default_factory=list)
    source: str = Field(min_length=1)
    source_item_ids: list[str] = Field(min_length=1)
    segments: list[Segment] = Field(min_length=1, max_length=32)
    guid: str | None = None
    translation_label: str = "Translation"
    answer_label: str = "Answer"


class Scripts(Model):
    episodes: list[Script] = Field(default_factory=list)
