from __future__ import annotations
import html
import re
from pathlib import Path
import sqlite3
import tempfile
import zipfile
import genanki

from .common import check, guid, local_file, read, write
from .dialogue import load_document
from .quality import load_artifacts, note_media, run_qa, source_description, expand_media

CSS = "body{font:20px/1.6 -apple-system,sans-serif;text-align:left;padding:20px}img,audio{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #aaa;padding:8px}label{display:block;padding:8px}section{margin:24px 0}"


def preview_media(source):
    def attribute(match):
        name = match.group(3)
        if name.startswith("#"):
            return match.group(0)
        return match.group(1) + match.group(2) + "../media/" + name + match.group(2)

    source = re.sub(r"((?:src|href)\s*=\s*)([\"'])([^\"']+)\2", attribute, source, flags=re.I)
    return re.sub(
        r"\[sound:([^\]]+)\]",
        lambda m: '<audio controls src="../media/' + html.escape(m.group(1), quote=True) + '"></audio>',
        source,
        flags=re.I,
    )


def build(root, output, check_audio=True):
    root, output = Path(root), Path(output)
    check(not output.exists(), "Output exists; choose a new release filename")
    report = run_qa(root, check_audio)
    check(report["passed"], "QA failed: " + "; ".join(report["errors"]))
    config, manifest, plan, draft, _ = load_artifacts(root)
    fields = [{"name": n} for n in ("Front", "Back", "Hint", "Extra", "Source", "Examples")]
    forward = {
        "name": "Forward",
        "qfmt": "{{Front}}",
        "afmt": '{{FrontSide}}<hr id="answer">{{Back}}<p>{{Extra}}</p><p>{{Examples}}</p><details><summary>Source</summary>{{Source}}</details>',
    }
    models = {}
    for offset, kind in enumerate(("basic", "reversed", "cloze")):
        templates = [forward]
        if kind == "reversed":
            templates = [
                forward,
                {
                    "name": "Reverse",
                    "qfmt": "{{Back}}",
                    "afmt": '{{FrontSide}}<hr id="answer">{{Front}}<p>{{Extra}}</p>',
                },
            ]
        if kind == "cloze":
            templates = [
                {
                    "name": "Cloze",
                    "qfmt": "{{cloze:Front}}",
                    "afmt": '{{cloze:Front}}<hr id="answer">{{Back}}<p>{{Extra}}</p><details><summary>Source</summary>{{Source}}</details>',
                }
            ]
        models[kind] = genanki.Model(
            config.model_id + offset,
            f"Deck Forge · {kind}",
            fields=fields,
            templates=templates,
            model_type=genanki.Model.CLOZE if kind == "cloze" else genanki.Model.FRONT_BACK,
            css=CSS,
        )
    deck = genanki.Deck(config.deck_id, config.name)
    media, expected, preview = set(), {}, []
    for note in draft.notes:
        tags = set(note.tags)
        if note.kind == "reference":
            tags.add("lingodeck::reference")
            if not any(t.startswith("lingodeck::material::") for t in tags):
                tags.add("lingodeck::material::theory")
        source = source_description(note.source_item_ids, plan, manifest)
        if note.provenance:
            source += "\n" + note.provenance
        identity = guid(config, note)
        values = [note.front, note.back, note.hint, note.extra, html.escape(source), note.examples]
        deck.add_note(
            genanki.Note(
                model=models["basic" if note.kind == "reference" else note.kind],
                guid=identity,
                fields=values,
                tags=sorted(tags),
            )
        )
        expected[identity] = values
        media.update(expand_media(root / "media", note_media(note)))
        preview.append(
            f"<section><h2>{html.escape(note.id)} · {html.escape(note.kind)}</h2><div>{note.front}</div><details><summary>Answer / theory</summary>{note.back}</details><small>{html.escape(source)}</small></section>"
        )
    ready = root / "dialogues.json"
    if ready.exists():
        _, rows = load_document(ready)
        dialogue_model = genanki.Model(
            config.model_id + 3,
            "Deck Forge · Dialogue v1",
            fields=[{"name": n} for n in ("Front", "Back", "Audio", "Source")],
            templates=[
                {
                    "name": "Episode",
                    "qfmt": "<h1>{{Front}}</h1>{{Audio}}",
                    "afmt": '{{FrontSide}}<hr id="answer">{{Back}}<small>{{Source}}</small>',
                }
            ],
            css=CSS,
        )
        bindings = read(root / "sources/listening-bindings.json")["episodes"]
        for e, identity, markup, files in rows:
            source = (
                source_description(bindings[e["id"]]["source_item_ids"], plan, manifest) + "\n" + e["source"]
            )
            values = [html.escape(e["title"]), markup, "[sound:" + e["audio"] + "]", html.escape(source)]
            deck.add_note(
                genanki.Note(
                    model=dialogue_model,
                    guid=identity,
                    fields=values,
                    tags=sorted(set(e["tags"]) | {"lingodeck::dialogue"}),
                )
            )
            expected[identity] = values
            media.update(files)
            preview.append(markup)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as tmp:
        staged = Path(tmp) / "deck.apkg"
        package = genanki.Package(deck)
        package.media_files = [str(local_file(root / "media", n)) for n in sorted(media)]
        package.write_to_file(str(staged))
        with zipfile.ZipFile(staged) as archive:
            mapping = __import__("json").loads(archive.read("media"))
            check(set(mapping.values()) == media, "Package media manifest differs")
            for key, name in mapping.items():
                check(
                    archive.read(key) == local_file(root / "media", name).read_bytes(),
                    "Media bytes changed during packaging",
                )
            db_path = Path(tmp) / "collection.sqlite"
            db_path.write_bytes(archive.read("collection.anki2"))
        with sqlite3.connect(db_path) as db:
            notes = db.execute("SELECT guid, flds FROM notes").fetchall()
            check(len(notes) == len(expected), "Packaged note count differs")
            for identity, values in notes:
                check(values.split("\x1f") == expected[identity], "Packaged field/GUID mismatch")
            card_count = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        staged.replace(output)
    # CSP keeps authored preview content offline even before import into LingoDeck.
    preview_html = (
        "<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; media-src 'self'; font-src 'self'; base-uri 'none'\"><title>Deck review</title><style>"
        + CSS
        + "</style><h1>"
        + html.escape(config.name)
        + "</h1>"
        + preview_media("".join(preview))
    )
    (root / "reports/preview.html").write_text(preview_html, encoding="utf-8")
    result = {
        "output": str(output.resolve()),
        "notes": len(expected),
        "anki_cards": card_count,
        "media_files": len(media),
        "qa": report,
        "manual_review": "Not automatically asserted: open preview, listen, check Anki/LingoDeck",
    }
    write(root / "reports/release.json", result)
    return result
