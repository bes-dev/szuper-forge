#!/usr/bin/env python3
"""Offline authoring validator/packager for the NEW synchronized dialogue v1 profile.
Validation uses the standard library. Building additionally needs genanki.
Audio verification needs ffprobe + ffmpeg. No network calls or TTS generation.
"""

import argparse
import hashlib
import html
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile


class Invalid(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Invalid(message)


def text(value, label):
    require(isinstance(value, str) and bool(value.strip()), f"{label}: nonempty string required")
    require(all(ord(c) >= 32 or c in "\n\t\r" for c in value), f"{label}: forbidden control character")
    return value.strip()


def number(value, label):
    require(type(value) in (int, float) and math.isfinite(value), f"{label}: finite number required")
    return value


def keys(obj, required, optional, label):
    require(isinstance(obj, dict), f"{label}: object required")
    require(not (set(required) - obj.keys()), f"{label}: missing {sorted(set(required) - obj.keys())}")
    require(
        not (obj.keys() - set(required) - set(optional)),
        f"{label}: unknown keys {sorted(obj.keys() - set(required) - set(optional))}",
    )


def media_name(value):
    value = text(value, "media filename")
    require(
        value not in (".", "..") and not any(c in value for c in "/\\:%\0"), f"Unsafe media name: {value}"
    )
    return value


def identity(deck, episode):
    if "guid" in episode:
        guid = text(episode["guid"], "guid")
        require(not any(c.isspace() for c in guid), "guid must not contain whitespace")
        return guid
    # Never include editable title/text/tags in the identity seed.
    seed = f"szuper-dialogue-v1:{deck['id']}:{episode['id']}"
    return hashlib.sha256(seed.encode()).hexdigest()[:20]


def validate_html(source):
    """Validate parser structure plus the stricter complete-sync authoring profile.
    Returns all declared local media names. Not a validator for arbitrary Anki HTML.
    """
    require(len(source.encode()) <= 2_000_000, "HTML exceeds 2,000,000 UTF-8 bytes")
    require(
        not any(s in source.lower() for s in ("<!doctype", "<!entity", "<script")),
        "Forbidden HTML declaration/script",
    )
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        raise Invalid(f"Invalid XML-compatible HTML: {exc}") from exc
    count = 0

    def walk(node, depth):
        nonlocal count
        count += 1
        require(depth <= 32 and count < 10_000, "HTML tree exceeds parser limits")
        for child in node:
            walk(child, depth + 1)

    walk(root, 1)

    def value(node):
        return "".join(node.itertext()).strip() if node is not None else ""

    def child(node, tag=None, kind=None):
        return next(
            (
                n
                for n in node
                if (tag is None or n.tag == tag) and (kind is None or n.get("data-kind") == kind)
            ),
            None,
        )

    require(
        root.tag == "article" and root.get("data-kind") == "dialogue" and root.get("data-version") == "1",
        "Expected dialogue article v1",
    )
    require(bool(value(child(root, "h1"))), "Missing title")
    language = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
    for attr in ("lang", "data-translation-lang"):
        code = root.get(attr, "")
        require(
            code != "und" and language.fullmatch(code),
            f"{attr}: declare a real BCP-47 language (syntax check only)",
        )
    files = {media_name(root.get("data-audio"))}
    try:
        duration = float(root.get("data-duration", ""))
    except (ValueError, TypeError) as exc:
        raise Invalid("Master duration required") from exc
    require(math.isfinite(duration) and duration > 0, "Master duration must be positive")
    sections = [s for s in root if s.tag == "section" and s.get("data-kind") == "segment"]
    require(1 <= len(sections) <= 32, "Expected 1–32 segments")
    ids = set()
    previous_start, previous_end = -1.0, -1.0
    for section in sections:
        sid = text(section.get("data-id"), "segment id")
        require(sid not in ids, f"Duplicate segment id: {sid}")
        ids.add(sid)
        audio = child(section, "audio")
        files.add(media_name(audio.get("src") if audio is not None else None))
        transcript = child(section, kind="transcript")
        phrases = [p for p in transcript if p.tag == "p"] if transcript is not None else []
        require(bool(phrases), f"{sid}: transcript required")
        for phrase in phrases:
            require(bool(value(phrase)), f"{sid}: empty phrase")
            text(phrase.get("data-speaker"), f"{sid}: speaker")
            text(phrase.get("data-translation"), f"{sid}: phrase translation")
            try:
                start, end = float(phrase.get("data-start", "")), float(phrase.get("data-end", ""))
            except (ValueError, TypeError) as exc:
                raise Invalid(f"{sid}: every phrase needs start/end seconds") from exc
            require(
                math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration + 0.05,
                f"{sid}: invalid phrase range",
            )
            require(
                start > previous_start and start >= previous_end - 0.001,
                f"{sid}: ambiguous overlap/order; fix actual alignment",
            )
            previous_start, previous_end = start, end
            for word in phrase:
                if word.tag == "span" and "data-gloss" in word.attrib:
                    require(bool(value(word)), "Empty glossed word")
                    text(word.get("data-gloss"), "word translation")
                    if "data-lemma" in word.attrib:
                        text(word.get("data-lemma"), "word lemma")
            if phrase.get("data-audio") is not None:
                files.add(media_name(phrase.get("data-audio")))
        q = child(section, "fieldset", "question")
        require(q is not None and bool(value(child(q, "legend"))), f"{sid}: question required")
        kind = q.get("data-type", "choice")
        require(kind in ("choice", "true-false", "select"), f"{sid}: unknown question type")
        options = [o for o in q if o.tag == "label"]
        require(2 <= len(options) <= 8, f"{sid}: expected 2–8 options")
        option_ids = [text(o.get("data-id"), "option id") for o in options]
        option_texts = [value(o) for o in options]
        require(len(set(option_ids)) == len(options), f"{sid}: duplicate option id")
        require(
            all(option_texts) and len(set(option_texts)) == len(options),
            f"{sid}: empty/duplicate option text",
        )
        require(
            all(o.get("data-correct") in ("true", "false") for o in options),
            f"{sid}: explicit true/false required",
        )
        correct = sum(o.get("data-correct") == "true" for o in options)
        require(0 < correct < len(options), f"{sid}: need correct and incorrect choices")
        require(kind == "select" or correct == 1, f"{sid}: expected exactly one correct choice")
        require(kind != "true-false" or len(options) == 2, f"{sid}: true-false requires two choices")
        require(
            bool(value(child(section, kind="explanation"))), f"{sid}: explanation required for new authoring"
        )
    return files


def word_glosses(phrase):
    """Authoring offsets are Unicode code points, converted to spans for native parsers."""
    items = phrase.get("words", [])
    require(isinstance(items, list), "phrase.words must be an array")
    previous = 0
    for word in items:
        keys(word, ("start", "end", "translation"), ("lemma",), "word")
        start, end = word["start"], word["end"]
        require(type(start) is int and type(end) is int, "word offsets must be integers")
        require(previous <= start < end <= len(phrase["text"]), "word ranges overlap or are outside phrase")
        require(phrase["text"][start:end].strip() == phrase["text"][start:end] and bool(phrase["text"][start:end].strip()), "word must not include boundary whitespace")
        text(word["translation"], "word.translation")
        if "lemma" in word:
            text(word["lemma"], "word.lemma")
        previous = end
    return items


def phrase_markup(transcript, attrs, phrase):
    paragraph = ET.SubElement(transcript, "p", attrs)
    words = word_glosses(phrase)
    if not words:
        paragraph.text = phrase["text"]
        return
    paragraph.text = phrase["text"][:words[0]["start"]]
    for index, word in enumerate(words):
        attributes = {"data-gloss": word["translation"]}
        if "lemma" in word:
            attributes["data-lemma"] = word["lemma"]
        span = ET.SubElement(paragraph, "span", attributes)
        span.text = phrase["text"][word["start"]:word["end"]]
        following = words[index + 1]["start"] if index + 1 < len(words) else len(phrase["text"])
        span.tail = phrase["text"][word["end"]:following]


def markup(episode):
    # Attribute/text escaping is delegated to the XML serializer.
    attrs = {
        "data-kind": "dialogue",
        "data-version": "1",
        "lang": episode["language"],
        "data-translation-lang": episode["translation_language"],
        "data-audio": episode["audio"],
        "data-duration": str(episode["duration"]),
    }
    root = ET.Element("article", attrs)
    ET.SubElement(root, "h1").text = episode["title"]
    ET.SubElement(root, "p", {"data-kind": "intro"}).text = episode["intro"]
    for segment in episode["segments"]:
        section = ET.SubElement(root, "section", {"data-kind": "segment", "data-id": segment["id"]})
        ET.SubElement(section, "audio", {"controls": "controls", "src": segment["audio"]})
        transcript = ET.SubElement(section, "div", {"data-kind": "transcript"})
        for phrase in segment["phrases"]:
            attrs = {
                "data-speaker": phrase["speaker"],
                "data-start": str(phrase["start"]),
                "data-end": str(phrase["end"]),
                "data-translation": phrase["translation"],
            }
            for key in ("audio", "pronunciation", "pronunciation_system"):
                if key in phrase:
                    attrs["data-" + key.replace("_", "-")] = phrase[key]
            phrase_markup(transcript, attrs, phrase)
            details = ET.SubElement(transcript, "details")
            ET.SubElement(details, "summary").text = episode.get("translation_label", "Translation")
            ET.SubElement(details, "p").text = phrase["translation"]
        if segment.get("translation"):
            ET.SubElement(section, "div", {"data-kind": "translation", "hidden": "hidden"}).text = segment[
                "translation"
            ]
        question = segment["question"]
        fieldset = ET.SubElement(
            section, "fieldset", {"data-kind": "question", "data-type": question["type"]}
        )
        ET.SubElement(fieldset, "legend").text = question["prompt"]
        for option in question["options"]:
            ET.SubElement(
                fieldset, "label", {"data-id": option["id"], "data-correct": str(option["correct"]).lower()}
            ).text = option["text"]
        ET.SubElement(section, "p", {"data-kind": "explanation"}).text = question["explanation"]
        solution = ET.SubElement(section, "details")
        ET.SubElement(solution, "summary").text = episode.get("answer_label", "Answer")
        ET.SubElement(solution, "p").text = " · ".join(o["text"] for o in question["options"] if o["correct"])
    return ET.tostring(root, encoding="unicode", short_empty_elements=False)


def load_document(path):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    doc = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_pairs)
    keys(doc, ("deck", "episodes"), (), "document")
    deck = doc["deck"]
    keys(deck, ("id", "name", "model_id"), (), "deck")
    for key in ("id", "model_id"):
        require(
            type(deck[key]) is int and 0 < deck[key] < 2**53, f"deck.{key}: positive exact integer required"
        )
    text(deck["name"], "deck.name")
    require(isinstance(doc["episodes"], list) and bool(doc["episodes"]), "episodes must be a nonempty list")
    ids, guids = set(), set()
    result = []
    for e in doc["episodes"]:
        keys(
            e,
            (
                "id",
                "title",
                "intro",
                "language",
                "translation_language",
                "audio",
                "duration",
                "source",
                "tags",
                "segments",
            ),
            ("guid", "translation_label", "answer_label"),
            "episode",
        )
        eid = text(e["id"], "episode.id")
        require(eid not in ids, f"Duplicate episode id: {eid}")
        ids.add(eid)
        for key in (
            "title",
            "intro",
            "language",
            "translation_language",
            "audio",
            "source",
            "translation_label",
            "answer_label",
        ):
            if key in e:
                text(e[key], f"{eid}.{key}")
        number(e["duration"], f"{eid}.duration")
        require(isinstance(e["tags"], list), f"{eid}: tags must be an array")
        require(
            all(isinstance(t, str) and t and not any(c.isspace() for c in t) for t in e["tags"]),
            f"{eid}: tags must be nonempty tokens",
        )
        require(
            not any(t.lower() == "szuper::reference" for t in e["tags"]),
            f"{eid}: cannot mix reference and dialogue",
        )
        require(isinstance(e["segments"], list), f"{eid}: segments must be an array")
        for s in e["segments"]:
            keys(s, ("id", "audio", "phrases", "question"), ("translation",), f"{eid}.segment")
            text(s["id"], "segment.id")
            text(s["audio"], "segment.audio")
            if "translation" in s:
                text(s["translation"], "segment.translation")
            require(isinstance(s["phrases"], list), "phrases must be an array")
            for phrase in s["phrases"]:
                keys(
                    phrase,
                    ("speaker", "text", "translation", "start", "end"),
                    ("audio", "pronunciation", "pronunciation_system", "words"),
                    "phrase",
                )
                for key in set(phrase) - {"start", "end", "words"}:
                    text(phrase[key], f"phrase.{key}")
                number(phrase["start"], "phrase.start")
                number(phrase["end"], "phrase.end")
            q = s["question"]
            keys(q, ("type", "prompt", "options", "explanation"), (), "question")
            for key in ("type", "prompt", "explanation"):
                text(q[key], f"question.{key}")
            require(isinstance(q["options"], list), "question.options must be an array")
            for o in q["options"]:
                keys(o, ("id", "text", "correct"), (), "option")
                text(o["id"], "option.id")
                text(o["text"], "option.text")
                require(type(o["correct"]) is bool, "option.correct must be a JSON boolean")
        source = markup(e)
        files = validate_html(source)
        guid = identity(deck, e)
        require(guid not in guids, f"Duplicate GUID: {guid}")
        guids.add(guid)
        result.append((e, guid, source, files))
    return deck, result


def verify_media(base, names, episodes, check_audio):
    base = base.resolve()
    durations = {}
    for name in sorted(names):
        path = base / name
        require(
            path.resolve().parent == base and path.is_file() and path.stat().st_size > 0,
            f"Missing/empty/nonlocal media: {name}",
        )
        if check_audio:
            raw = subprocess.check_output(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                text=True,
            )
            seconds = float(raw.strip())
            require(math.isfinite(seconds) and seconds > 0, f"Invalid audio duration: {name}")
            subprocess.run(
                ["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-map", "0:a:0", "-f", "null", "-"],
                check=True,
                stdout=subprocess.DEVNULL,
            )
            durations[name] = seconds
    if check_audio:
        for episode in episodes:
            require(
                abs(durations[episode["audio"]] - episode["duration"]) <= 0.2,
                f"{episode['id']}: declared master duration differs from decoded file by >0.2s",
            )
    return durations


def package(deck, rows, base, destination):
    import genanki

    require(
        not destination.exists(),
        "Output exists; choose a new output path (source/identity is independent of filename)",
    )
    model = genanki.Model(
        deck["model_id"],
        "Szuper Dialogue v1 · Basic",
        fields=[{"name": n} for n in ("Front", "Back", "Audio", "Source")],
        templates=[
            {
                "name": "Episode",
                "qfmt": "<h1>{{Front}}</h1>{{Audio}}",
                "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
            }
        ],
        css='body{font:20px/1.6 -apple-system,sans-serif;text-align:left;padding:16px}audio{width:100%}section{margin:24px 0}label{display:block;padding:8px}fieldset{border:1px solid #aaa}details{margin:8px 0}[data-kind="explanation"]{font-size:.9em}',
    )
    target = genanki.Deck(deck["id"], deck["name"])
    media = set()
    for episode, guid, source, files in rows:
        target.add_note(
            genanki.Note(
                model=model,
                guid=guid,
                fields=[
                    html.escape(episode["title"]),
                    source,
                    "[sound:" + episode["audio"] + "]",
                    html.escape(episode["source"]),
                ],
                tags=sorted(set(episode["tags"]) | {"szuper::dialogue"}),
            )
        )
        media.update(files)
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Stage, then validate the actual archive before publishing the final file.
    with tempfile.TemporaryDirectory(dir=destination.parent) as tmp:
        staged = Path(tmp) / "deck.apkg"
        output = genanki.Package(target)
        output.media_files = [str(base / n) for n in sorted(media)]
        output.write_to_file(str(staged))
        with zipfile.ZipFile(staged) as archive:
            manifest = json.loads(archive.read("media"))
            require(set(manifest.values()) == media, "Packaged media differs from declarations")
            for entry, name in manifest.items():
                require(
                    archive.read(entry) == (base / name).read_bytes(), f"Packaged media bytes differ: {name}"
                )
            db_path = Path(tmp) / "collection.sqlite"
            db_path.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(db_path) as db:
            notes = db.execute("SELECT guid, flds, tags FROM notes").fetchall()
            require(len(notes) == len(rows), "Packaged note count differs")
            originals = {guid: source for _, guid, source, _ in rows}
            for guid, fields, tags in notes:
                require(fields.split("\x1f")[1] == originals[guid], "Packaged Back/GUID differs")
                require("szuper::dialogue" in tags.split(), "Packaged dialogue tag missing")
                validate_html(fields.split("\x1f")[1])
            require(
                db.execute("SELECT COUNT(*) FROM cards WHERE ord=0").fetchone()[0] == len(rows),
                "Expected one forward card per episode",
            )
        staged.replace(destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "build"):
        p = sub.add_parser(command)
        p.add_argument("--input", required=True, type=Path)
        p.add_argument("--media", required=True, type=Path)
        p.add_argument("--check-audio", action="store_true")
        if command == "build":
            p.add_argument("--output", required=True, type=Path)
    p = sub.add_parser("validate-html", help="Validate the new synchronous profile, not every legacy variant")
    p.add_argument("html", type=Path)
    p.add_argument("--media", required=True, type=Path)
    p.add_argument("--check-audio", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "validate-html":
            source = args.html.read_text(encoding="utf-8")
            files = validate_html(source)
            root = ET.fromstring(source)
            episodes = [
                {
                    "id": args.html.stem,
                    "audio": root.get("data-audio"),
                    "duration": float(root.get("data-duration")),
                }
            ]
            verify_media(args.media, files, episodes, args.check_audio)
            print(json.dumps({"valid": True, "media_files": len(files), "audio_verified": args.check_audio}))
            return
        deck, rows = load_document(args.input)
        files = set().union(*(r[3] for r in rows))
        verify_media(args.media, files, [r[0] for r in rows], args.check_audio)
        if args.command == "build":
            package(deck, rows, args.media, args.output)
        print(
            json.dumps(
                {
                    "valid": True,
                    "deck": deck["name"],
                    "episodes": [
                        {
                            "id": e["id"],
                            "guid": guid,
                            "language": e["language"],
                            "translation_language": e["translation_language"],
                            "seconds": e["duration"],
                            "phrases": sum(len(s["phrases"]) for s in e["segments"]),
                            "questions": len(e["segments"]),
                        }
                        for e, guid, _, _ in rows
                    ],
                    "media_files": len(files),
                    "audio_verified": args.check_audio,
                    "output": str(args.output) if args.command == "build" else None,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except (Invalid, OSError, ValueError, subprocess.SubprocessError, ImportError) as exc:
        parser.exit(1, f"Error: {exc}\n")


if __name__ == "__main__":
    main()
