"""Inspect working-tree files without following links or reading Git metadata."""

import os
import re
import stat
from pathlib import Path

SKIP_DIRECTORIES = frozenset({
    ".git", "build", "out", "node_modules", ".venv", "venv", "__pycache__",
    ".vs", ".idea", ".pytest_cache", ".mypy_cache",
})
MAX_TEXT_BYTES = 5 * 1024 * 1024
MAX_MARKER_DETAILS = 1000
MARKERS = re.compile(r"\b(TODO|FIXME|BUG)\b", re.IGNORECASE)


def is_link(path: Path) -> bool:
    """Also exclude Windows junctions and other reparse points."""
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def inspect_text(path: Path) -> tuple[str | None, str | None]:
    with path.open("rb") as source:
        data = source.read(MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES:
        return None, "over_size_limit"
    if b"\x00" in data:
        return None, "binary"
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None, "decode_error"
    if any(ord(char) < 32 and char not in "\r\n\t\f" for char in text):
        return None, "binary"
    return text, None


def scan_repository(root: Path, excluded_paths: tuple[Path, ...] = ()) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError("Target must be an existing directory.")
    excluded = {path.resolve() for path in excluded_paths}
    result = {
        "file_count": 0, "directory_count": 0, "total_bytes": 0,
        "text_file_count": 0, "nonempty_lines": 0, "extension_counts": {},
        "largest_files": [], "markers": [],
        "marker_counts": {"TODO": 0, "FIXME": 0, "BUG": 0},
        "marker_details_truncated": False, "skipped_directories": [],
        "skipped_links": [], "skipped_text": [], "warnings": [],
    }

    def warn(error: OSError) -> None:
        name = Path(error.filename) if error.filename else root
        try:
            label = name.relative_to(root).as_posix()
        except ValueError:
            label = name.name
        result["warnings"].append({"path": label, "reason": type(error).__name__})

    largest = []
    for current, directories, filenames in os.walk(root, topdown=True, onerror=warn, followlinks=False):
        folder = Path(current)
        kept = []
        for name in sorted(directories):
            path = folder / name
            relative = path.relative_to(root).as_posix()
            try:
                if name.lower() in SKIP_DIRECTORIES or path.resolve() in excluded:
                    result["skipped_directories"].append(relative)
                elif is_link(path):
                    result["skipped_links"].append(relative)
                else:
                    kept.append(name)
                    result["directory_count"] += 1
            except OSError as error:
                warn(error)
        directories[:] = kept
        for name in sorted(filenames):
            path = folder / name
            relative = path.relative_to(root).as_posix()
            try:
                if name.lower() == ".git" or path.resolve() in excluded:
                    continue
                if is_link(path):
                    result["skipped_links"].append(relative)
                    continue
                info = path.stat()
                if not stat.S_ISREG(info.st_mode):
                    continue
                result["file_count"] += 1
                result["total_bytes"] += info.st_size
                extension = path.suffix.lower() or "[no extension]"
                counts = result["extension_counts"]
                counts[extension] = counts.get(extension, 0) + 1
                largest.append({"path": relative, "bytes": info.st_size})
                largest = sorted(largest, key=lambda item: (-item["bytes"], item["path"]))[:10]
                text, reason = inspect_text(path)
                if reason:
                    result["skipped_text"].append({"path": relative, "reason": reason})
                    continue
                result["text_file_count"] += 1
                for number, line in enumerate(text.splitlines(), 1):
                    if line.strip():
                        result["nonempty_lines"] += 1
                    for match in MARKERS.finditer(line):
                        marker = match.group().upper()
                        result["marker_counts"][marker] += 1
                        if len(result["markers"]) < MAX_MARKER_DETAILS:
                            result["markers"].append({"path": relative, "line": number, "marker": marker, "excerpt": line.strip()[:180]})
                        else:
                            result["marker_details_truncated"] = True
            except OSError as error:
                warn(error)
    result["largest_files"] = largest
    result["extension_counts"] = dict(sorted(result["extension_counts"].items()))
    checks = {}
    for label, candidates, directory in (
        ("README.md", ("README.md",), False),
        (".gitignore", (".gitignore",), False),
        ("LICENSE", ("LICENSE",), False),
        ("tests/ or test/", ("tests", "test"), True),
    ):
        found = False
        for candidate in candidates:
            path = root / candidate
            try:
                exists = path.is_dir() if directory else path.is_file()
                if exists and not is_link(path):
                    found = True
            except OSError as error:
                warn(error)
        checks[label] = found
    result["engineering_files"] = checks
    return result
