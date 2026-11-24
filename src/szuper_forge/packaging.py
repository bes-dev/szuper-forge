from __future__ import annotations
from contextlib import closing
import errno
import hashlib
import itertools
import json
import os
import shutil
import time
import html
import re
from pathlib import Path
import sqlite3
import tempfile
import zipfile
import genanki

from .common import check, digest, guid, local_file, read, write
from .editorial import rank, tag_values
from .dialogue import load_document
from .quality import load_artifacts, note_media, run_qa, source_descriptions, expand_media

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


def practice_preview(note):
    prompt, answer = note.front, note.back
    if note.kind == "cloze":
        cloze = re.compile(r"\{\{c([1-9]\d*)::(.+?)(?:::(.*?))?\}\}", re.S)
        blocks = []
        for index in dict.fromkeys(match[1] for match in cloze.finditer(prompt)):
            cue = cloze.sub(lambda m: (m[3] or "…") if m[1] == index else m[2], prompt)
            filled = cloze.sub(lambda m: m[2], prompt)
            blocks.append((cue, filled + "<p>" + answer + "</p>"))
    else:
        blocks = [(prompt, answer)]
        if note.kind == "reversed":
            blocks.append((answer, prompt))
    hint = f"<p>{note.hint}</p>" if note.hint else ""
    return "".join(
        f"<details><summary>{cue}</summary>{hint}<div>{result}</div><p>{note.extra}</p><p>{note.examples}</p></details>"
        for cue, result in blocks
    )


def publish_package(staged, output):
    try:
        os.link(staged, output)
    except FileExistsError as exc:
        raise ValueError("Output exists; choose a new release filename") from exc
    except OSError as exc:
        if exc.errno not in {errno.ENOTSUP, errno.EPERM, errno.ENOSYS}:
            raise
        # Some removable volumes lack hard links. Reserve the name exclusively
        # before replacing our own empty file with the verified package.
        with output.open("xb"):
            pass
        try:
            staged.replace(output)
        except OSError:
            output.unlink(missing_ok=True)
            raise


def build(root, output, check_audio=True):
    root, output = Path(root), Path(output)
    check(not output.exists(), "Output exists; choose a new release filename")
    output.parent.mkdir(parents=True, exist_ok=True)
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    with (
        tempfile.TemporaryDirectory(dir=output.parent) as package_dir,
        tempfile.TemporaryDirectory(dir=reports) as report_dir,
    ):
        staged = Path(package_dir) / "deck.apkg"
        pending = Path(report_dir)
        result = prepare_release(root, output, staged, pending, check_audio)
        names = ["provenance.json", "preview.html", "release.json"]
        prior = {}
        for name in names:
            target = reports / name
            if target.exists():
                # Keep the previous reports available if a later rename fails.
                backup = pending / ("prior-" + name)
                shutil.copyfile(target, backup)
                prior[name] = backup
        published = []
        publish_package(staged, output)
        try:
            for name in names:
                (pending / name).replace(reports / name)
                published.append(name)
        except OSError:
            for name in reversed(published):
                if name in prior:
                    prior[name].replace(reports / name)
                else:
                    (reports / name).unlink()
            output.unlink()
            raise
        return result


def prepare_release(root, output, staged, pending, check_audio):
    report = run_qa(root, check_audio)
    check(report["passed"], "QA failed: " + "; ".join(report["errors"]))
    config, manifest, plan, draft, _ = load_artifacts(root)
    fields = [{"name": n} for n in ("Front", "Back", "Hint", "Extra", "Source", "Examples")]
    forward = {
        "name": "Forward",
        "qfmt": "{{Front}}",
        "afmt": '{{FrontSide}}<hr id="answer">{{Back}}<p>{{Extra}}</p><p>{{Examples}}</p>',
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
                    "afmt": '{{cloze:Front}}<hr id="answer">{{Back}}<p>{{Extra}}</p>',
                }
            ]
        models[kind] = genanki.Model(
            config.model_id + offset,
            f"Szuper Forge · {kind}",
            fields=fields,
            templates=templates,
            model_type=genanki.Model.CLOZE if kind == "cloze" else genanki.Model.FRONT_BACK,
            css=CSS,
        )
    deck = genanki.Deck(config.deck_id, config.name)
    media, expected, preview = set(), {}, []
    evidence, fingerprints, chapters = {}, {}, []
    previous_path = root / "reports/release.json"
    previous = None
    previous_times = {}
    release_time = int(time.time())
    if previous_path.exists():
        release = read(previous_path)
        if release.get("project_uid") == config.uid:
            previous = release.get("note_fingerprints")
            previous_times = release.get("note_modifications", {})
            release_time = max(release_time, release.get("release_time", 0) + 1)
    evidence_by_item = source_descriptions(plan, manifest)

    def evidence_for(item_ids):
        return "\n".join(dict.fromkeys(line for item_id in item_ids for line in evidence_by_item[item_id]))

    for note in draft.notes:
        tags = set(note.tags)
        if note.kind == "reference":
            tags.add("szuper::reference")
            if not any(t.startswith("szuper::material::") for t in tags):
                tags.add("szuper::material::theory")
        source = evidence_for(note.source_item_ids)
        if note.provenance:
            source += "\n" + note.provenance
        identity = guid(config, note)
        evidence[identity] = source
        values = [note.front, note.back, note.hint, note.extra, "", note.examples]
        fingerprints[identity] = digest([note.kind, values, sorted(tags)])
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
        if note.kind == "reference":
            section = next(iter(tag_values(tags, "section")), "").replace("_", " ")
            chapters.append((section, rank(tags, "course-order"), rank(tags, "order"), note))
        else:
            preview.append(practice_preview(note))
    ready = root / "dialogues.json"
    if ready.exists():
        _, rows = load_document(ready)
        dialogue_model = genanki.Model(
            config.model_id + 3,
            "Szuper Forge · Dialogue v1",
            fields=[{"name": n} for n in ("Front", "Back", "Audio", "Source")],
            templates=[
                {
                    "name": "Episode",
                    "qfmt": "<h1>{{Front}}</h1>{{Audio}}",
                    "afmt": '{{FrontSide}}<hr id="answer">{{Back}}',
                }
            ],
            css=CSS,
        )
        bindings = read(root / "sources/listening-bindings.json")["episodes"]
        for e, identity, markup, files in rows:
            source = evidence_for(bindings[e["id"]]["source_item_ids"]) + "\n" + e["source"]
            evidence[identity] = source
            values = [html.escape(e["title"]), markup, "[sound:" + e["audio"] + "]", ""]
            fingerprints[identity] = digest(["dialogue", values, sorted(e["tags"])])
            deck.add_note(
                genanki.Note(
                    model=dialogue_model,
                    guid=identity,
                    fields=values,
                    tags=sorted(set(e["tags"]) | {"szuper::dialogue"}),
                )
            )
            expected[identity] = values
            media.update(files)
            preview.append(markup)
    with tempfile.TemporaryDirectory(dir=staged.parent) as tmp:
        package = genanki.Package(deck)
        mapping = {str(i): name for i, name in enumerate(sorted(media))}
        db_path = Path(tmp) / "collection.anki2"
        modifications = {
            identity: previous_times.get(identity, release_time)
            if previous and previous.get(identity) == fingerprint
            else release_time
            for identity, fingerprint in fingerprints.items()
        }
        # Own the staging database so source content is also cleaned up on failure.
        with closing(sqlite3.connect(db_path)) as db, db:
            package.write_to_db(db.cursor(), release_time, itertools.count(release_time * 1000))
            db.executemany("UPDATE notes SET mod=? WHERE guid=?", ((v, k) for k, v in modifications.items()))
        with zipfile.ZipFile(staged, "w") as archive:
            archive.write(db_path, "collection.anki2")
            archive.writestr("media", json.dumps(mapping, ensure_ascii=False))
            for key, name in mapping.items():
                archive.write(local_file(root / "media", name), key)
        with zipfile.ZipFile(staged) as archive:
            check(json.loads(archive.read("media")) == mapping, "Package media manifest differs")
            for key, name in mapping.items():
                with archive.open(key) as packed, local_file(root / "media", name).open("rb") as source_file:
                    check(
                        hashlib.file_digest(packed, "sha256").digest()
                        == hashlib.file_digest(source_file, "sha256").digest(),
                        "Media bytes changed during packaging",
                    )
            with archive.open("collection.anki2") as packed, db_path.open("rb") as source_file:
                check(
                    hashlib.file_digest(packed, "sha256").digest()
                    == hashlib.file_digest(source_file, "sha256").digest(),
                    "Packaged database differs",
                )
        with closing(sqlite3.connect(db_path)) as db:
            notes = db.execute("SELECT guid, flds FROM notes").fetchall()
            check(len(notes) == len(expected), "Packaged note count differs")
            for identity, values in notes:
                check(values.split("\x1f") == expected[identity], "Packaged field/GUID mismatch")
            card_count = db.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    section_ranks = {}
    for section, course_rank, _, _ in chapters:
        section_ranks[section] = min(section_ranks.get(section, float("inf")), course_rank)
    contents = []
    for section in sorted(section_ranks, key=section_ranks.get):
        if section:
            contents.append(f"<h2>{html.escape(section)}</h2>")
        for _, _, _, chapter in sorted((c for c in chapters if c[0] == section), key=lambda c: c[2]):
            contents.append(f"<details><summary>{chapter.front}</summary>{chapter.back}</details>")
    write(pending / "provenance.json", evidence)
    # CSP keeps authored preview content offline even before import into Szuper.
    preview_html = (
        "<!doctype html><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; media-src 'self'; font-src 'self'; base-uri 'none'\"><title>Deck review</title><style>"
        + CSS
        + "</style><h1>"
        + html.escape(config.name)
        + "</h1>"
        + preview_media("".join(contents + preview))
    )
    (pending / "preview.html").write_text(preview_html, encoding="utf-8")
    result = {
        "output": str(output.resolve()),
        "notes": len(expected),
        "anki_cards": card_count,
        "media_files": len(media),
        "qa": report,
        "project_uid": config.uid,
        "release_time": release_time,
        "note_modifications": modifications,
        "note_fingerprints": fingerprints,
        "note_changes": None
        if previous is None
        else {
            "added": sorted(fingerprints.keys() - previous.keys()),
            "updated": sorted(
                k for k in fingerprints.keys() & previous.keys() if fingerprints[k] != previous[k]
            ),
            "removed": sorted(previous.keys() - fingerprints.keys()),
        },
        "manual_review": "Not automatically asserted: open preview, listen, check Anki/Szuper",
    }
    write(pending / "release.json", result)
    return {
        key: value for key, value in result.items() if key not in {"note_fingerprints", "note_modifications"}
    }
