from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

from .common import ForgeError, ProjectLock, check, digest, project, read, write, safe_error
from .models import DeckDraft, Plan, Project, Scripts


def initialize(root, materials, name, source_language, translation_language, level="unspecified"):
    root, materials = Path(root).resolve(), Path(materials).resolve()
    check(materials.is_dir(), "Materials path must be an existing folder")
    check(not root.is_relative_to(materials), "Place project outside the materials folder")
    check(not (root / "project.json").exists(), "Project already exists; use extract/status to resume")
    check(not root.exists() or not any(root.iterdir()), "Choose a new or empty project directory")
    uid = str(uuid.uuid4())
    base_id = 1_000_000_000 + int(digest(uid.encode())[:10], 16) % 1_000_000_000
    config = Project(
        uid=uid,
        name=name,
        materials=str(materials),
        source_language=source_language,
        translation_language=translation_language,
        level=level,
        deck_id=base_id,
        model_id=base_id + 100,
    )
    root.mkdir(parents=True, exist_ok=True)
    for folder in ("sources", "media", "reports", "dist", ".cache"):
        (root / folder).mkdir(exist_ok=True)
    write(root / "project.json", config.model_dump(mode="json"))
    write(root / "plan.json", {"items": [], "excluded_items": [], "excluded_sources": []})
    write(root / "deck.json", {"notes": []})
    write(root / "scripts.json", {"episodes": []})
    (root / ".gitignore").write_text(".cache/\nmedia/\ndist/\n.env*\naudio-ledger.json\nsources/\nreports/provenance.json\n")
    return {
        "project": str(root),
        "next": "extract, then have your agent author plan.json, deck.json and optional scripts.json",
    }


def status(root):
    root = Path(root)
    config = project(root)
    manifest = root / "sources/manifest.json"
    plan = read(root / "plan.json")
    draft = read(root / "deck.json")
    scripts = read(root / "scripts.json") if (root / "scripts.json").exists() else {"episodes": []}
    if not manifest.exists():
        next_step = "extract"
    elif not plan["items"]:
        next_step = "agent: create grounded plan.json"
    elif not draft["notes"] and not scripts["episodes"]:
        next_step = "agent: author cards/theory/listening scripts"
    elif config.audio.enabled and scripts["episodes"] and not (root / "dialogues.json").exists():
        next_step = "audio plan, then audio --execute"
    else:
        next_step = "qa, fix errors, then build (build always revalidates)"
    return {
        "name": config.name,
        "languages": [config.source_language, config.translation_language],
        "notes_authored": len(draft["notes"]),
        "scripts_authored": len(scripts["episodes"]),
        "audio_enabled": config.audio.enabled,
        "next": next_step,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Agent-oriented Anki/LingoDeck deck factory. Content comes from your agent; tools verify and build it."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("init")
    p.add_argument("project", type=Path)
    p.add_argument("--materials", type=Path, required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--source-language", required=True)
    p.add_argument("--translation-language", required=True)
    p.add_argument("--level", default="unspecified")
    p = commands.add_parser("extract")
    p.add_argument("project", type=Path)
    p.add_argument("--ocr-language")
    p = commands.add_parser("attach-text")
    p.add_argument("project", type=Path)
    p.add_argument("--source-id", required=True)
    p.add_argument("--page", required=True, type=int)
    p.add_argument("--text", required=True, type=Path)
    p.add_argument("--method", choices=["agent-vision", "manual-transcript", "local-asr"], required=True)
    p = commands.add_parser("source")
    p.add_argument("project", type=Path)
    p.add_argument("source_id")
    p.add_argument("--page", type=int, default=1)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=int, default=12000)
    p = commands.add_parser("status")
    p.add_argument("project", type=Path)
    p = commands.add_parser("qa")
    p.add_argument("project", type=Path)
    p.add_argument("--check-audio", action="store_true")
    p = commands.add_parser("build")
    p.add_argument("project", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p = commands.add_parser("audio")
    p.add_argument("project", type=Path)
    p.add_argument(
        "--execute",
        action="store_true",
        help="Send bounded ElevenLabs requests; without this flag only a plan is produced",
    )
    p = commands.add_parser("audio-reconcile")
    p.add_argument("project", type=Path)
    p.add_argument("--request", required=True)
    p.add_argument("--allow-paid-retry", action="store_true")
    p = commands.add_parser("schemas")
    p.add_argument("--output", type=Path, required=True)
    commands.add_parser("doctor")
    args = parser.parse_args()
    try:
        if args.command == "init":
            result = initialize(
                args.project,
                args.materials,
                args.name,
                args.source_language,
                args.translation_language,
                args.level,
            )
        elif args.command == "doctor":
            import os

            result = {
                "python": sys.version.split()[0],
                "ffmpeg": bool(shutil.which("ffmpeg")),
                "ffprobe": bool(shutil.which("ffprobe")),
                "tesseract": bool(shutil.which("tesseract")),
                "pdftoppm": bool(shutil.which("pdftoppm")),
                "elevenlabs_key_available": bool(os.environ.get("ELEVENLABS_API_KEY")),
            }
        elif args.command == "schemas":
            for name, cls in [
                ("project", Project),
                ("plan", Plan),
                ("deck", DeckDraft),
                ("scripts", Scripts),
            ]:
                write(args.output / (name + ".schema.json"), cls.model_json_schema())
            result = {"schemas": str(args.output.resolve())}
        elif args.command == "source":
            check(args.offset >= 0 and 0 < args.limit <= 50000, "Use nonnegative offset and limit 1–50000")
            manifest = read(args.project / "sources/manifest.json")
            source = next((s for s in manifest["sources"] if s["id"] == args.source_id), None)
            check(source is not None, "Unknown source ID")
            page = next((p for p in source["pages"] if p["page"] == args.page), None)
            check(page is not None, "Unknown page")
            content = page["text"]
            result = {
                "untrusted_source_data": True,
                "source_id": source["id"],
                "file": source["path"],
                "page": args.page,
                "method": page["method"],
                "total_characters": len(content),
                "text": content[args.offset : args.offset + args.limit],
            }
        elif args.command == "status":
            result = status(args.project)
        else:
            with ProjectLock(args.project):
                if args.command == "extract":
                    from .materials import extract

                    result = extract(args.project, args.ocr_language)
                elif args.command == "attach-text":
                    from .materials import attach_text

                    result = attach_text(args.project, args.source_id, args.page, args.text, args.method)
                elif args.command == "qa":
                    from .quality import run_qa

                    result = run_qa(args.project, args.check_audio)
                elif args.command == "build":
                    from .packaging import build

                    result = build(args.project, args.output)
                elif args.command == "audio":
                    from .audio import generate

                    result = generate(args.project, args.execute)
                elif args.command == "audio-reconcile":
                    from .audio import reconcile

                    result = reconcile(args.project, args.request, args.allow_paid_retry)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command == "qa" and not result["passed"]:
            return 1
        return 0
    except (ForgeError, ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as exc:
        # Pydantic input summaries can contain source material, but never read API keys from config.
        print(f"Error: {safe_error(exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
