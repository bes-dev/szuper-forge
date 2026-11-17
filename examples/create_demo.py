#!/usr/bin/env python3
"""Create a reproducible, source-grounded demo. No credentials/network/audio generation."""

import json
from pathlib import Path
import sys
from deck_forge.cli import initialize
from deck_forge.common import read, write
from deck_forge.materials import extract


def create(root):
    root = Path(root)
    materials = Path(__file__).parent / "materials"
    initialize(root, materials, "English at a café", "en", "ru", "A1")
    extract(root)
    sid = read(root / "sources/manifest.json")["sources"][0]["id"]
    items = [
        ("tea", "tea — чай", "Recall the word tea"),
        ("coffee", "coffee — кофе", "Recall the word coffee"),
        ("milk", "milk — молоко", "Recall the word milk"),
        ("politeness", "Use “please” to make a request polite.", "Make a polite request"),
        ("dialogue", "The customer wants tea, not coffee.", "Understand a café order"),
    ]
    write(
        root / "plan.json",
        {
            "items": [
                {
                    "id": i,
                    "topic": "Everyday::Cafe",
                    "objective": objective,
                    "refs": [{"source_id": sid, "page": 1, "quote": quote}],
                }
                for i, quote, objective in items
            ]
        },
    )
    notes = [
        {
            "id": word,
            "kind": "reversed",
            "front": word,
            "back": meaning,
            "tags": ["Everyday::Cafe"],
            "source_item_ids": [word],
        }
        for word, meaning in [("tea", "чай"), ("coffee", "кофе"), ("milk", "молоко")]
    ]
    notes += [
        {
            "id": "please-cloze",
            "kind": "cloze",
            "front": "Tea, {{c1::please}}.",
            "back": "Чай, пожалуйста.",
            "tags": ["Everyday::Cafe"],
            "source_item_ids": ["politeness"],
        },
        {
            "id": "polite-request-reference",
            "kind": "reference",
            "front": "Polite requests",
            "back": "<h1>Polite requests</h1><p>Use <strong>please</strong> to make a request polite.</p><blockquote>Tea, please.<br />Чай, пожалуйста.</blockquote>",
            "tags": ["Everyday::Cafe", "lingodeck::section::usage", "lingodeck::order::10"],
            "source_item_ids": ["politeness"],
        },
        {
            "id": "cafe-fact",
            "kind": "basic",
            "front": "What does the customer want?",
            "back": "Tea",
            "tags": ["Everyday::Cafe"],
            "source_item_ids": ["dialogue"],
        },
    ]
    write(root / "deck.json", {"notes": notes})
    write(
        root / "scripts.json",
        {
            "episodes": [
                {
                    "id": "cafe-listening",
                    "title": "At the café",
                    "intro": "Послушайте заказ посетителя.",
                    "language": "en",
                    "translation_language": "ru",
                    "tags": ["Everyday::Cafe"],
                    "source": "Authored practice scene based on the supplied café lesson.",
                    "source_item_ids": ["tea", "milk", "politeness", "dialogue"],
                    "translation_label": "Перевод",
                    "answer_label": "Ответ",
                    "segments": [
                        {
                            "id": "order",
                            "phrases": [
                                {
                                    "speaker": "Customer",
                                    "text": "Tea, please.",
                                    "translation": "Чай, пожалуйста.",
                                },
                                {"speaker": "Server", "text": "With milk?", "translation": "С молоком?"},
                            ],
                            "question": {
                                "type": "choice",
                                "prompt": "Что заказал посетитель?",
                                "options": [
                                    {"id": "tea", "text": "Чай", "correct": True},
                                    {"id": "coffee", "text": "Кофе", "correct": False},
                                ],
                                "explanation": "Посетитель говорит «Tea, please».",
                            },
                        }
                    ],
                }
            ]
        },
    )
    return root


if __name__ == "__main__":
    print(json.dumps({"project": str(create(sys.argv[1]))}))
