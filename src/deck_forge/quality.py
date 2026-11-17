from __future__ import annotations
from pathlib import Path
import re
import subprocess

from .common import check, digest, guid, local_file, normalized, project, read, write, safe_error
from .dialogue import load_document, verify_media
from .materials import html_text
from .models import DeckDraft, Plan, Scripts


def load_artifacts(root):
    root = Path(root)
    config = project(root)
    manifest = read(root / "sources/manifest.json")
    plan = Plan.model_validate(read(root / "plan.json"))
    draft = DeckDraft.model_validate(read(root / "deck.json"))
    scripts = (
        Scripts.model_validate(read(root / "scripts.json")) if (root / "scripts.json").exists() else Scripts()
    )
    return config, manifest, plan, draft, scripts


def validate_scripts(config, scripts):
    # Validate every quiz/translation before a paid request. No invented timings are saved.
    from .dialogue import media_name

    ids = set()
    for e in scripts.episodes:
        check(e.id not in ids, f"Duplicate script id: {e.id}")
        ids.add(e.id)
        for code in (e.language, e.translation_language):
            check(
                code != "und" and re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", code),
                "Declare real BCP-47 languages",
            )
        check(not any(not t or any(c.isspace() for c in t) for t in e.tags), f"{e.id}: invalid tags")
        check(
            not any(t.lower() == "lingodeck::reference" for t in e.tags), "Dialogue cannot also be reference"
        )
        segment_ids = set()
        for s in e.segments:
            check(s.id not in segment_ids, f"{e.id}: duplicate segment id")
            segment_ids.add(s.id)
            q = s.question
            correct = sum(o.correct for o in q.options)
            check(0 < correct < len(q.options), f"{e.id}/{s.id}: need correct and incorrect options")
            check(q.type == "select" or correct == 1, "Single-choice question needs one correct option")
            check(q.type != "true-false" or len(q.options) == 2, "true-false needs two options")
            check(len({o.id for o in q.options}) == len(q.options), "Duplicate option IDs")
            check(len({o.text for o in q.options}) == len(q.options), "Duplicate option text")
            check(all(p.translation and p.text for p in s.phrases), "Every phrase needs text and translation")
        media_name("ep-" + digest(e.id.encode())[:12] + "-master.wav")


def note_media(note):
    fields = "\n".join((note.front, note.back, note.hint, note.extra, note.examples))
    names = set(re.findall(r"\[sound:([^\]]+)\]", fields, re.I))
    names.update(re.findall(r"(?:src|href)\s*=\s*[\"\']([^\"\']+)[\"\']", fields, re.I))
    names.update(re.findall(r"url\(\s*[\"\']?([^\s)\"\']+)", fields, re.I))
    return {n for n in names if not n.startswith("#")}


def expand_media(root, names):
    result = set()
    pending = list(names)
    while pending:
        name = pending.pop()
        if name in result:
            continue
        path = local_file(root, name)
        result.add(name)
        if path.suffix.lower() == ".css":
            css = path.read_text(encoding="utf-8")
            nested = re.findall(r"url\(\s*[\"']?([^\s)\"']+)", css, re.I)
            nested += re.findall(r"@import\s+[\"']([^\"']+)[\"']", css, re.I)
            pending.extend(n for n in nested if not n.startswith("#"))
    return result


def source_description(item_ids, plan, manifest):
    items = {i.id: i for i in plan.items}
    sources = {s["id"]: s for s in manifest["sources"]}
    lines = []
    for iid in item_ids:
        for ref in items[iid].refs:
            name = sources[ref.source_id]["path"]
            lines.append(f"{name}, p. {ref.page or 1}: {ref.quote}")
    return "\n".join(dict.fromkeys(lines))


def run_qa(root, check_audio=False, preparing_audio=False):
    root = Path(root)
    errors, warnings = [], []
    report = {
        "passed": False,
        "stage": "preaudio" if preparing_audio else "release",
        "errors": errors,
        "warnings": warnings,
        "coverage_kind": "declared inventory coverage, not proof of complete source understanding",
    }
    try:
        config, manifest, plan, draft, scripts = load_artifacts(root)
        validate_scripts(config, scripts)
        sources = {s["id"]: s for s in manifest["sources"]}
        check(len(sources) == len(manifest["sources"]), "Duplicate source IDs")
        excluded_sources = {e.id: e.reason for e in plan.excluded_sources}
        check(set(excluded_sources) <= sources.keys(), "Exclusion references unknown source")
        materials = Path(config.materials).resolve()
        for source in sources.values():
            original = (materials / source["path"]).resolve()
            check(
                original.is_relative_to(materials) and original.is_file(), f"Source missing: {source['path']}"
            )
            check(
                digest(original.read_bytes()) == source["sha256"],
                f"Source changed; rerun extract: {source['path']}",
            )
            if source.get("error") or not source["pages"] or any(not p["text"] for p in source["pages"]):
                check(
                    source["id"] in excluded_sources,
                    f"Unread source/pages: {source['path']}; extract/OCR/transcribe or explicitly exclude with a reason",
                )
        items = {i.id: i for i in plan.items}
        check(len(items) == len(plan.items), "Duplicate plan item IDs")
        referenced_sources = set()
        for item in plan.items:
            for ref in item.refs:
                check(ref.source_id in sources, f"{item.id}: unknown source")
                check(ref.source_id not in excluded_sources, f"{item.id}: references excluded source")
                source = sources[ref.source_id]
                pages = [p for p in source["pages"] if ref.page is None or p["page"] == ref.page]
                check(
                    any(normalized(ref.quote) in normalized(p["text"]) for p in pages),
                    f"{item.id}: evidence not found on referenced page",
                )
                referenced_sources.add(ref.source_id)
        check(
            sources.keys() <= referenced_sources | excluded_sources.keys(),
            "Some sources are neither used nor explicitly excluded",
        )
        if excluded_sources:
            warnings.append("Explicitly excluded sources: " + ", ".join(excluded_sources))
        excluded_items = {e.id: e.reason for e in plan.excluded_items}
        check(set(excluded_items) <= items.keys(), "Exclusion references unknown plan item")
        covered, identities, note_ids, fronts = set(), set(), set(), {}
        all_media = set()
        reverse_fronts = set()
        for note in draft.notes:
            check(note.id not in note_ids, f"Duplicate note ID: {note.id}")
            note_ids.add(note.id)
            identity = guid(config, note)
            check(identity not in identities, "Duplicate note GUID")
            identities.add(identity)
            check(not any(c.isspace() for c in identity), "GUID cannot contain whitespace")
            check(set(note.source_item_ids) <= items.keys(), f"{note.id}: unknown source_item_ids")
            covered.update(note.source_item_ids)
            check(
                not any(t.lower() == "lingodeck::dialogue" for t in note.tags),
                "Use scripts.json/dialogues.json for dialogue notes",
            )
            check(
                note.kind == "reference" or not any(t.lower() == "lingodeck::reference" for t in note.tags),
                "reference tag requires reference kind",
            )
            check(
                not re.search(r"<script\b|<iframe\b|<!ENTITY|<!DOCTYPE", note.front + note.back, re.I),
                f"{note.id}: executable/external document markup is unsupported",
            )
            if note.kind == "cloze":
                check(
                    bool(re.search(r"\{\{c[1-9]\d*::[^{}]+\}\}", note.front)),
                    f"{note.id}: no valid cloze in Front",
                )
            elif note.kind != "reference":
                front = normalized(html_text(note.front)).casefold()
                back = normalized(html_text(note.back)).casefold()
                check(front and back, f"{note.id}: empty visible prompt/answer")
                check(front not in fronts, f"{note.id}: duplicate/ambiguous front; disambiguate the sense")
                fronts[front] = back
                if note.kind == "reversed":
                    check(
                        back not in reverse_fronts,
                        f"{note.id}: ambiguous reverse prompt; disambiguate or use Basic",
                    )
                    reverse_fronts.add(back)
            for name in expand_media(root / "media", note_media(note)):
                local_file(root / "media", name)
                all_media.add(name)
        rows = []
        bindings = {}
        ready = root / "dialogues.json"
        if ready.exists() and not preparing_audio:
            deck_meta, rows = load_document(ready)
            check(
                deck_meta["id"] == config.deck_id and deck_meta["model_id"] == config.model_id + 3,
                "Dialogue deck/model IDs differ from project",
            )
            binding_doc = read(root / "sources/listening-bindings.json")
            bindings = binding_doc["episodes"]
            if "speech_config_sha256" in binding_doc:
                check(
                    binding_doc["speech_config_sha256"]
                    == digest({"model": config.audio.model, "voices": config.audio.voices}),
                    "Speech config changed; regenerate from the selected voices/model",
                )
            if scripts.episodes:
                check(
                    binding_doc.get("scripts_sha256") == digest(scripts.model_dump(mode="json")),
                    "Listening scripts changed; regenerate audio or provide updated authored alignment",
                )
            for e, identity, _, files in rows:
                check(identity not in identities, "Duplicate GUID between normal notes and episodes")
                identities.add(identity)
                check(e["id"] not in note_ids, "Note/episode IDs must be globally unique")
                ids = bindings[e["id"]]["source_item_ids"]
                check(ids and set(ids) <= items.keys(), "Dialogue has missing/unknown grounding items")
                covered.update(ids)
                all_media.update(files)
            verify_media(
                root / "media", set().union(*(r[3] for r in rows)), [r[0] for r in rows], check_audio
            )
        if preparing_audio:
            for e in scripts.episodes:
                check(set(e.source_item_ids) <= items.keys(), f"{e.id}: unknown source_item_ids")
                covered.update(e.source_item_ids)
        if scripts.episodes and not preparing_audio:
            published = {e["id"] for e, _, _, _ in rows}
            missing = {e.id for e in scripts.episodes} - published
            if missing:
                check(
                    not config.audio.enabled,
                    "Audio enabled but episodes are not generated: " + ", ".join(sorted(missing)),
                )
                warnings.append("Listening omitted (audio disabled): " + ", ".join(sorted(missing)))
        check(covered or draft.notes or rows, "No learning content to build")
        check(not (covered & excluded_items.keys()), "Item cannot be both covered and excluded")
        missing = items.keys() - covered - excluded_items.keys()
        check(not missing, "Uncovered plan items: " + ", ".join(sorted(missing)))
        if excluded_items:
            warnings.append("Explicitly excluded inventory items: " + ", ".join(excluded_items))
        report.update(
            notes=len(draft.notes),
            listening_episodes=len(rows),
            media_files=len(all_media),
            inventory_items=len(items),
            covered_items=len(covered),
            excluded_items=excluded_items,
            inventory_coverage=round(len(covered) / len(items), 4),
            audio_decoded=check_audio and bool(rows),
            input_sha256=digest(
                {
                    "project": config.model_dump(),
                    "manifest": manifest,
                    "plan": plan.model_dump(),
                    "notes": draft.model_dump(),
                    "scripts": scripts.model_dump(),
                    "dialogues": read(ready) if ready.exists() else None,
                }
            ),
        )
    except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        errors.append(safe_error(exc))
    report["passed"] = not errors
    write(root / ("reports/preaudio-qa.json" if preparing_audio else "reports/qa.json"), report)
    return report
