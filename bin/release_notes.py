"""Read and maintain the current draft entry in RELEASE_NOTES.md."""

import re
from pathlib import Path
from typing import Optional


_HEADING_PATTERN = re.compile(r"^# (?:\[(?P<linked>[^]]+)\]\([^)]*\)|(?P<plain>.+))$", re.MULTILINE)
_SEPARATOR_PATTERN = re.compile(r"\n---\s*\n")


def _top_heading(content: str) -> Optional[re.Match[str]]:
    """Return the first top-level heading, ignoring leading blank lines."""
    match = _HEADING_PATTERN.search(content)
    if match and not content[:match.start()].strip():
        return match
    return None


def _heading_title(match: re.Match[str]) -> str:
    return match.group("linked") or match.group("plain") or ""


def _expected_title(module_name: str, version: str) -> str:
    return f"{module_name} {version}"


def format_draft_entry(module_name: str, version: str, notes: str) -> str:
    """Format the unpublished release entry that will become the top record."""
    return f"# {_expected_title(module_name, version)}\n\n{notes.strip()}\n\n---\n"


def upsert_draft_entry(
    notes_path: Path, module_name: str, version: str, notes: str
) -> None:
    """Create or replace the top draft entry for a release version.

    A matching top entry is left untouched when its notes are unchanged;
    otherwise it is replaced so repeated preparation updates its notes. A different (or missing) top entry leaves the history
    intact and gets a new draft prepended to it.
    """
    content = notes_path.read_text(encoding="utf-8") if notes_path.exists() else ""
    draft = format_draft_entry(module_name, version, notes)
    heading = _top_heading(content)

    if heading and _heading_title(heading) == _expected_title(module_name, version):
        separator = _SEPARATOR_PATTERN.search(content, heading.end())
        body_end = separator.start() if separator else len(content)
        if content[heading.end():body_end].strip() == notes.strip():
            # Keeping existing notes must not normalize whitespace or headings.
            return
        end = separator.end() if separator else len(content)
        updated = draft + content[end:].lstrip("\n")
    else:
        updated = draft + ("\n" + content.lstrip("\n") if content else "")

    notes_path.write_text(updated, encoding="utf-8")


def read_top_entry(notes_path: Path, module_name: str, version: str) -> Optional[str]:
    """Return a matching top draft body, or ``None`` when it is unavailable."""
    if not notes_path.is_file():
        return None
    content = notes_path.read_text(encoding="utf-8")
    heading = _top_heading(content)
    if not heading or _heading_title(heading) != _expected_title(module_name, version):
        return None

    separator = _SEPARATOR_PATTERN.search(content, heading.end())
    end = separator.start() if separator else len(content)
    body = content[heading.end():end].strip()
    return body or None
