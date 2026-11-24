"""Editorial review cues for authored material. Semantic judgments stay with the author."""

import re
from pathlib import Path

from .materials import html_text

SOURCE_CUE = re.compile(
    r"according to (?:the |this )?(?:slide|handout|worksheet)|(?:see|consult) (?:page|slide)\s+\d+"
    r"|(?:как указано|по данным|согласно|на) (?:в |на )?(?:методичк|слайд|страниц[еуы] \d)"
    r"|(?:в|из) (?:методичк|пособии)|\bметодичка\s+\d|\bстраница\s+\d+"
    r"|\ba (?:tananyag|dia|képaláírás) szerint\b|\ba (?:tananyagban|dián)\b|\ba dia\b",
    re.I,
)
LEVEL = re.compile(r"^([ABC][12](?:[–-][ABC][12])?)\s*·\s*", re.I)
NUMBERED = re.compile(r"^(?:(?:lesson|chapter|урок|глава)\s+\d+\b|\d+[.)]\s+)", re.I)


def tag_values(tags, name):
    prefix = "szuper::" + name + "::"
    return [tag[len(prefix) :] for tag in tags if tag.lower().startswith(prefix)]


def rank(tags, name):
    values = tag_values(tags, name)
    if len(values) == 1 and re.fullmatch(r"[0-9]+", values[0]) and len(values[0]) <= 18:
        number = int(values[0])
        if number > 0:
            return number
    return float("inf")


def source_cues(manifest):
    # Match known filenames only in learner text, never in local media attributes.
    names = {Path(s["path"]).name for s in manifest["sources"]}
    patterns = [SOURCE_CUE.pattern, *(re.escape(n) for n in names if "." in n)]
    return re.compile("|".join(patterns), re.I)


def review_text(key, text, cues, warnings):
    if cues.search(html_text(text)):
        message = f"{key}: possible reference to an outside document; read the prompt on its own"
        warnings.append(message)


def review_title(key, title, tags, warnings):
    title = html_text(title).strip()
    level = LEVEL.match(title)
    levels = tag_values(tags, "level")
    if levels and (not level or levels != [level[1]]):
        warnings.append(f"{key}: align the visible level and the level tag")
    topics = tag_values(tags, "topic")
    if len(topics) == 1 and level:
        topic_level = LEVEL.match(topics[0].replace("_", " "))
        if topic_level and topic_level[1] != level[1]:
            warnings.append(f"{key}: chapter or episode level differs from its topic")
    if NUMBERED.match(title[level.end() :] if level else title):
        warnings.append(f"{key}: put sequence numbers in order tags; use a meaningful visible title")
    for name in ("order", "course-order"):
        if tag_values(tags, name) and rank(tags, name) == float("inf"):
            warnings.append(f"{key}: use one positive integer in {name}")


def review_notes(notes, cues, warnings):
    groups = {g for n in notes if n.kind != "reference" for g in tag_values(n.tags, "practice")}
    chapters = [
        n for n in notes if n.kind == "reference" and tag_values(n.tags, "material") in ([], ["theory"])
    ]
    ordered = any(tag_values(n.tags, "course-order") for n in chapters)
    for n in notes:
        for field in ("front", "back", "hint", "extra", "examples"):
            review_text(f"{n.id}.{field}", getattr(n, field), cues, warnings)
        for topic in (
            tag_values(n.tags, "topic")
            + tag_values(n.tags, "section")
            + [t for t in n.tags if not t.lower().startswith("szuper::")]
        ):
            review_text(f"{n.id}.topic", topic.replace("_", " "), cues, warnings)
        if n.kind in {"basic", "reversed"}:
            answer = html_text(n.back).strip()
            if n.hint and html_text(n.hint).strip().casefold() == answer.casefold():
                warnings.append(f"{n.id}.hint: the cue gives the full answer")
            if len([part for part in answer.split(",") if part.strip()]) >= 6:
                warnings.append(
                    f"{n.id}.back: long comma list; verify the retrieval target and partial-credit behavior"
                )
    positions = {}
    for chapter in chapters:
        review_title(chapter.id, chapter.front, chapter.tags, warnings)
        if ordered and not tag_values(chapter.tags, "course-order"):
            warnings.append(f"{chapter.id}: unranked chapter in an ordered course; verify its position")
        heading = re.search(r"<h1\b[^>]*>(.*?)</h1>", chapter.back, re.I | re.S)
        if heading and html_text(heading[1]).split() != html_text(chapter.front).split():
            warnings.append(f"{chapter.id}: visible chapter title and first heading differ")
        order = rank(chapter.tags, "order")
        if ordered and order == float("inf"):
            warnings.append(f"{chapter.id}: verify the reading order within its section")
        if order != float("inf"):
            position = (tuple(tag_values(chapter.tags, "section")), order)
            if position in positions:
                warnings.append(f"{chapter.id}: shares a reading position with {positions[position]}")
            positions[position] = chapter.id
        linked = tag_values(chapter.tags, "practice")
        if len(linked) > 1 or (linked and linked[0] not in groups):
            warnings.append(f"{chapter.id}: practice link needs one group with ordinary study cards")
