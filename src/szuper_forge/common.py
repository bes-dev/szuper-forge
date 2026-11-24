from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unicodedata
from .models import Project


class ForgeError(ValueError):
    pass


def check(condition, message):
    if not condition:
        raise ForgeError(message)


def read(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            check(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
        staging = Path(f.name)
    staging.replace(path)


def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def project(root):
    return Project.model_validate(read(Path(root) / "project.json"))


def normalized(text):
    return "".join(unicodedata.normalize("NFC", text).split())


def guid(config, note):
    return note.guid or digest(f"{config.uid}:{note.id}".encode())[:20]


def local_file(root, name):
    from .dialogue import media_name

    media_name(name)
    root = Path(root).resolve()
    path = (root / name).resolve()
    check(
        path.parent == root and path.is_file() and path.stat().st_size > 0, f"Missing/nonlocal media: {name}"
    )
    return path


class ProjectLock:
    def __init__(self, root):
        self.path = Path(root) / ".forge.lock"

    def __enter__(self):
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise ForgeError(
                "Another write operation is active. If it crashed, inspect and remove .forge.lock."
            ) from exc
        with os.fdopen(fd, "w") as f:
            f.write(str(os.getpid()))
        return self

    def __exit__(self, *args):
        self.path.unlink(missing_ok=True)


def safe_error(exc):
    from pydantic import ValidationError

    if isinstance(exc, ValidationError):
        return json.dumps(exc.errors(include_input=False, include_context=False), ensure_ascii=False)
    return str(exc)
