import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import zipfile

import pytest

from szuper_forge.cli import initialize
from szuper_forge.common import ForgeError, ProjectLock, read, write
from szuper_forge.materials import attach_text, extract, html_text
from szuper_forge.packaging import build
from szuper_forge.quality import run_qa


def notes_in_package(path):
    with zipfile.ZipFile(path) as archive:
        data = archive.read("collection.anki2")
    db_path = Path(path).with_suffix(".sqlite")
    db_path.write_bytes(data)
    with sqlite3.connect(db_path) as db:
        return db.execute("SELECT guid,flds,tags FROM notes ORDER BY guid").fetchall(), db.execute(
            "SELECT count(*) FROM cards"
        ).fetchone()[0]


def test_materials_to_real_mixed_anki_package_without_keys(demo, monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    qa = run_qa(demo)
    assert qa["passed"], qa
    assert qa["covered_items"] == 5
    assert qa["warnings"] and "omitted" in qa["warnings"][0]
    result = build(demo, demo / "dist/demo.apkg")
    notes, cards = notes_in_package(result["output"])
    assert len(notes) == 6 and cards == 9
    assert any("szuper::reference" in row[2] for row in notes)
    assert any("{{c1::please}}" in row[1] for row in notes)
    fields = next(f.split("\x1f") for _, f, _ in notes if f.startswith("tea\x1f"))
    assert fields[2] == fields[4] == ""
    evidence = read(demo / "reports/provenance.json")
    assert any("lesson.md" in entry and "tea — чай" in entry for entry in evidence.values())
    assert (demo / "reports/preview.html").exists()
    assert read(demo / "reports/release.json")["qa"]["passed"]


def test_guid_stability_when_content_and_topics_change(demo):
    first = demo / "dist/v1.apkg"
    build(demo, first)
    original, _ = notes_in_package(first)
    draft = read(demo / "deck.json")
    draft["notes"][0]["back"] = "чай / чайный напиток"
    draft["notes"][0]["tags"].append("Teacher::Lesson_2")
    write(demo / "deck.json", draft)
    second = demo / "dist/v2.apkg"
    changes = build(demo, second)["note_changes"]
    assert changes["added"] == changes["removed"] == []
    assert len(changes["updated"]) == 1
    updated, _ = notes_in_package(second)
    assert [n[0] for n in original] == [n[0] for n in updated]
    assert [n[1] for n in original] != [n[1] for n in updated]
    with pytest.raises(ForgeError, match="Output exists"):
        build(demo, first)


@pytest.mark.parametrize(
    "mutation,fragment",
    [
        (
            lambda p: p["items"][0]["refs"][0].update(quote="a fact not in this material"),
            "evidence not found",
        ),
        (lambda p: p["items"][0]["refs"][0].update(page=999), "evidence not found"),
        (lambda p: p["items"].append(dict(p["items"][0])), "Duplicate plan"),
        (lambda p: p["items"][0]["refs"][0].update(source_id="unknown"), "unknown source"),
    ],
)
def test_false_grounding_and_duplicate_inventory_block_release(demo, mutation, fragment):
    plan = read(demo / "plan.json")
    mutation(plan)
    write(demo / "plan.json", plan)
    report = run_qa(demo)
    assert not report["passed"] and fragment in report["errors"][0]
    with pytest.raises(ForgeError, match="QA failed"):
        build(demo, demo / "dist/invalid.apkg")
    assert not (demo / "dist/invalid.apkg").exists()


def test_uncovered_inventory_not_silently_dropped(demo):
    notes = read(demo / "deck.json")
    notes["notes"] = [n for n in notes["notes"] if n["id"] != "coffee"]
    write(demo / "deck.json", notes)
    assert "Uncovered plan items: coffee" in run_qa(demo)["errors"][0]
    plan = read(demo / "plan.json")
    plan["excluded_items"] = [{"id": "coffee", "reason": "Explicitly outside this release’s agreed scope"}]
    write(demo / "plan.json", plan)
    qa = run_qa(demo)
    assert qa["passed"] and qa["inventory_coverage"] == 0.8
    assert qa["excluded_items"]["coffee"]


def test_duplicate_and_ambiguous_prompts_block_release(demo):
    draft = read(demo / "deck.json")
    draft["notes"][1]["front"] = draft["notes"][0]["front"]
    write(demo / "deck.json", draft)
    assert "ambiguous front" in run_qa(demo)["errors"][0]


def test_missing_and_unsafe_media_block_release(demo):
    draft = read(demo / "deck.json")
    for name in ("missing.png", "../escape.png", "https://example.org/remote.png"):
        draft["notes"][4]["back"] = '<img src="' + name + '" />'
        write(demo / "deck.json", draft)
        assert not run_qa(demo)["passed"]


def test_changed_source_requires_reextraction_without_losing_note_ids(demo, tmp_path):
    # Copy teaching material before editing; original repository fixtures stay read-only.
    materials = tmp_path / "mutable-sources"
    materials.mkdir()
    config = read(demo / "project.json")
    source = Path(config["materials"]) / "lesson.md"
    (materials / "lesson.md").write_text(source.read_text())
    config["materials"] = str(materials)
    write(demo / "project.json", config)
    (materials / "lesson.md").write_text(source.read_text() + "\nAdditional teacher note.\n")
    ids = [n["id"] for n in read(demo / "deck.json")["notes"]]
    assert "Source changed" in run_qa(demo)["errors"][0]
    extract(demo)
    assert run_qa(demo)["passed"]
    assert [n["id"] for n in read(demo / "deck.json")["notes"]] == ids


def test_unread_and_unsupported_files_remain_visible(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    (materials / "scan.png").write_bytes(b"not decoded by initial inventory")
    (materials / "slides.pptx").write_bytes(b"unknown input")
    (materials / ".env").write_text("secret-not-learning-content")
    root = tmp_path / "project"
    initialize(root, materials, "Demo", "de", "pl")
    result = extract(root)
    assert result["unread_pages"] == 2
    sources = read(root / "sources/manifest.json")["sources"]
    assert {s["path"] for s in sources} == {"scan.png", "slides.pptx"}
    transcript = tmp_path / "read.txt"
    transcript.write_text("Guten Tag — dzień dobry")
    source = next(s for s in sources if s["path"] == "scan.png")
    attach_text(root, source["id"], 1, transcript, "agent-vision")
    extract(root)  # Unchanged source preserves attached agent transcription.
    updated = read(root / "sources/manifest.json")["sources"]
    assert next(s for s in updated if s["id"] == source["id"])["pages"][0]["text"] == transcript.read_text()


def test_docx_and_scanned_pdf_are_extracted_honestly(tmp_path):
    from docx import Document
    from pypdf import PdfWriter

    materials = tmp_path / "materials"
    materials.mkdir()
    doc = Document()
    doc.add_paragraph("A useful grammar rule.")
    doc.save(materials / "rule.docx")
    pdf = PdfWriter()
    pdf.add_blank_page(width=100, height=100)
    with (materials / "scan.pdf").open("wb") as f:
        pdf.write(f)
    root = tmp_path / "project"
    initialize(root, materials, "Rules", "en", "es")
    extract(root)
    sources = {s["path"]: s for s in read(root / "sources/manifest.json")["sources"]}
    assert "grammar rule" in sources["rule.docx"]["pages"][0]["text"]
    assert sources["scan.pdf"]["pages"][0]["method"] == "needs-ocr"


def test_source_html_is_data_not_executable():
    assert "steal" not in html_text("<script>steal()</script><p>Rule</p><style>css</style>")
    assert html_text("<p>One</p><p>Two</p>").split() == ["One", "Two"]


def test_project_must_not_overwrite_source_folder(tmp_path):
    materials = tmp_path / "materials"
    materials.mkdir()
    with pytest.raises(ForgeError, match="outside"):
        initialize(materials / "output", materials, "Deck", "en", "es")


def test_project_write_lock(demo):
    with ProjectLock(demo):
        with pytest.raises(ForgeError, match="Another write"):
            with ProjectLock(demo):
                pass
    assert not (demo / ".forge.lock").exists()


def test_cli_works_from_an_unrelated_working_directory(demo, tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "szuper_forge.cli", "status", str(demo)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["languages"] == ["en", "ru"]


def test_css_and_font_dependencies_are_packaged_and_preview_paths_work(demo):
    draft = read(demo / "deck.json")
    draft["notes"][4]["back"] = '<link rel="stylesheet" href="book.css" /><h1>Theory</h1>'
    write(demo / "deck.json", draft)
    (demo / "media/book.css").write_text(
        '@import "theme.css"; @font-face {font-family: x; src:url("book.woff2")}'
    )
    (demo / "media/theme.css").write_text("body {color: #333}")
    (demo / "media/book.woff2").write_bytes(b"font-container-fixture")
    output = demo / "dist/with-css.apkg"
    build(demo, output)
    with zipfile.ZipFile(output) as archive:
        media = json.loads(archive.read("media"))
        assert set(media.values()) == {"book.css", "theme.css", "book.woff2"}
    assert "../media/book.css" in (demo / "reports/preview.html").read_text()


def test_reversed_ambiguity_is_rejected(demo):
    draft = read(demo / "deck.json")
    draft["notes"][1]["back"] = draft["notes"][0]["back"]
    write(demo / "deck.json", draft)
    assert "ambiguous reverse prompt" in run_qa(demo)["errors"][0]


def test_invalid_config_never_echoes_accidentally_embedded_secret(demo):
    config = read(demo / "project.json")
    config["ELEVENLABS_API_KEY"] = "accidentally-entered-secret"
    write(demo / "project.json", config)
    report = run_qa(demo)
    assert not report["passed"]
    assert "accidentally-entered-secret" not in json.dumps(report)


def test_learner_templates_never_render_source_metadata(demo):
    output = demo / "dist/no-provenance-ui.apkg"
    build(demo, output)
    with zipfile.ZipFile(output) as archive:
        database = demo / "source-policy.sqlite"
        database.write_bytes(archive.read("collection.anki2"))
    with sqlite3.connect(database) as db:
        models = json.loads(db.execute("SELECT models FROM col").fetchone()[0])
        for model in models.values():
            for template in model["tmpls"]:
                assert "{{Source}}" not in template["qfmt"]
                assert "{{Source}}" not in template["afmt"]
        assert all("lesson.md" not in fields for (fields,) in db.execute("SELECT flds FROM notes"))


def test_editorial_review_and_chapter_sequence(demo):
    draft = read(demo / "deck.json")
    chapter = draft["notes"][4]
    earlier = dict(
        chapter,
        id="earlier",
        front="A1 · Поздороваться",
        back="<h1>A1 · Поздороваться</h1><p>Доброе утро!</p>",
        tags=[tag.replace("::10", "::5") for tag in chapter["tags"]],
    )
    draft["notes"].append(earlier)
    draft["notes"][0]["hint"] = "Как указано на слайде 4"
    chapter["tags"].remove("szuper::practice::cafe-order")
    chapter["tags"].append("szuper::practice::missing")
    draft["notes"][1]["examples"] = "I give a presentation on Fridays."
    write(demo / "deck.json", draft)
    qa = run_qa(demo)
    assert qa["passed"]
    assert any("tea.hint" in w for w in qa["warnings"])
    assert any("practice link" in w for w in qa["warnings"])
    assert not any("coffee.examples" in w for w in qa["warnings"])
    draft["notes"][0]["hint"] = ""
    chapter["tags"][-1] = "szuper::practice::cafe-order"
    write(demo / "deck.json", draft)
    build(demo, demo / "dist/ordered.apkg")
    preview = (demo / "reports/preview.html").read_text()
    assert preview.index("A1 · Поздороваться") < preview.index("A1 · Заказать напиток")
    assert "lesson.md" not in preview
    assert "{{c1::" not in preview
    assert "<summary>чай</summary>" in preview


def test_back_to_back_builds_only_advance_edited_note_timestamps(demo, monkeypatch):
    monkeypatch.setattr("szuper_forge.packaging.time.time", lambda: 1800000000)

    def revisions(name):
        path = demo / "dist" / name
        build(demo, path)
        notes_in_package(path)
        with sqlite3.connect(path.with_suffix(".sqlite")) as db:
            return dict(db.execute("select guid,mod from notes"))

    first = revisions("first.apkg")
    cards = read(demo / "deck.json")
    cards["notes"][0]["extra"] = "An alternative example."
    write(demo / "deck.json", cards)
    second = revisions("second.apkg")
    assert first.keys() == second.keys()
    assert sorted(second[k] - first[k] for k in first) == [0, 0, 0, 0, 0, 1]


def test_release_report_failure_preserves_previous_build(demo, monkeypatch):
    first = demo / "dist/first.apkg"
    build(demo, first)
    reports = demo / "reports"
    originals = {
        name: (reports / name).read_bytes() for name in ("release.json", "preview.html", "provenance.json")
    }
    dest = demo / "dist/second.apkg"
    replace = Path.replace

    def fail_last(self, target):
        if self.name == "release.json" and Path(target) == reports / "release.json":
            raise OSError("write failed")
        return replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_last)
    with pytest.raises(OSError, match="write failed"):
        build(demo, dest)
    assert not dest.exists()
    assert first.is_file()
    assert {name: (reports / name).read_bytes() for name in originals} == originals
