"""Read local Git history. Never fetch, push, or modify repository configuration."""

import os
import subprocess
import re
from datetime import datetime
from pathlib import Path


class GitError(Exception):
    pass


def parse_numstat_log(text: str) -> dict:
    """Parse NUL-delimited numstat output; never execute Git or inspect files."""
    commits, warnings = [], []
    current = None
    for index, raw in enumerate(text.split("\x00"), 1):
        record = raw.lstrip("\n")
        if not record:
            continue
        if record.startswith("commit:"):
            current = None
            fields = record[7:].split("\t")
            try:
                if len(fields) != 2 or not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", fields[0]):
                    raise ValueError
                date = datetime.fromisoformat(fields[1])
                if date.tzinfo is None:
                    raise ValueError
            except ValueError:
                warnings.append(f"Record {index}: invalid commit header; skipped.")
                continue
            current = {"hash": fields[0], "date": fields[1], "files": []}
            commits.append(current)
            continue
        fields = record.split("\t", maxsplit=2)
        if current is None or len(fields) != 3 or not fields[2]:
            warnings.append(f"Record {index}: malformed or orphan numstat; skipped.")
            continue
        additions, deletions, path = fields
        binary = additions == deletions == "-"
        if not binary and not (re.fullmatch(r"[0-9]+", additions) and re.fullmatch(r"[0-9]+", deletions)):
            warnings.append(f"Record {index}: invalid line counts; skipped.")
            continue
        try:
            current["files"].append({"path": path, "additions": None if binary else int(additions),
                                     "deletions": None if binary else int(deletions), "binary": binary})
        except ValueError:
            warnings.append(f"Record {index}: line count too large; skipped.")
    return {"commits": commits, "warnings": warnings}


def run_git(root: Path, *arguments: str, allow_failure: bool = False) -> subprocess.CompletedProcess:
    # Ignore inherited routing variables that could point at a different repository.
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0", "LC_ALL": "C"})
    try:
        result = subprocess.run(
            ["git", "--no-pager", "-c", "color.ui=false", "-c", "log.showSignature=false",
             "-c", "i18n.logOutputEncoding=UTF-8", "-C", str(root), *arguments],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=30, check=False, env=environment,
        )
    except FileNotFoundError as error:
        raise GitError("Git is not installed or is not on PATH.") from error
    except subprocess.TimeoutExpired as error:
        raise GitError("Git command timed out after 30 seconds.") from error
    except OSError as error:
        raise GitError(f"Cannot start Git: {error.strerror or type(error).__name__}.") from error
    if result.returncode and not allow_failure:
        detail = result.stderr.strip() or "Git returned a nonzero exit status."
        raise GitError(f"Git command failed: {detail}")
    return result


def build_file_hotspots(commits: list[dict]) -> list[dict]:
    """Aggregate exact paths; a binary observation makes line totals unknown."""
    stats, seen = {}, set()
    for commit in commits:
        for record in commit["files"]:
            path = record["path"]
            item = stats.setdefault(path, {"path": path, "commit_count": 0, "additions": 0,
                                          "deletions": 0, "churn": 0, "last_changed_at": commit["date"], "binary": False})
            key = (commit["hash"], path)
            if key not in seen:
                item["commit_count"] += 1
                seen.add(key)
            if datetime.fromisoformat(commit["date"]) > datetime.fromisoformat(item["last_changed_at"]):
                item["last_changed_at"] = commit["date"]
            item["binary"] |= record["binary"]
            if item["binary"]:
                item["additions"] = item["deletions"] = item["churn"] = None
            else:
                item["additions"] += record["additions"]
                item["deletions"] += record["deletions"]
                item["churn"] = item["additions"] + item["deletions"]
    return sorted(stats.values(), key=lambda item: (item["binary"], -(item["churn"] or 0), -item["commit_count"], item["path"]))


def analyze_hotspots(root: Path, git: dict, limit: int = 100) -> dict:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("git-limit must be a positive integer.")
    result = {"analyzed_commits": 0, "requested_limit": limit, "hotspots": [], "binary_files": [],
              "warnings": [], "head": git["head"]}
    if git["shallow"]:
        result["warnings"].append("Shallow clone: only locally available history can be analyzed.")
    if not git["head"]:
        return result
    log = run_git(root, "log", "--numstat", "-z", "--no-renames", "--no-ext-diff", "--no-textconv",
                  "--diff-merges=off", "--root", "--format=commit:%H%x09%aI%x00", "-n", str(limit), git["head"], "--")
    parsed = parse_numstat_log(log.stdout)
    files = build_file_hotspots(parsed["commits"])
    result.update(analyzed_commits=len({c["hash"] for c in parsed["commits"]}),
                  hotspots=[f for f in files if not f["binary"]][:10],
                  binary_files=[f for f in files if f["binary"]])
    result["warnings"].extend(parsed["warnings"])
    if log.stderr.strip():
        result["warnings"].append(log.stderr.strip())
    return result


def repository_root(target: Path) -> Path:
    result = run_git(target, "rev-parse", "--show-toplevel", allow_failure=True)
    if result.returncode:
        detail = result.stderr.strip()
        if "not a git repository" in detail.lower():
            raise GitError("Target is not a Git working-tree repository.")
        if "must be run in a work tree" in detail.lower():
            raise GitError("Bare repositories are not supported; select a working tree.")
        raise GitError(f"Cannot inspect repository: {detail}")
    return Path(result.stdout.strip()).resolve()


def analyze_git(root: Path) -> dict:
    head = run_git(root, "rev-parse", "--verify", "--quiet", "HEAD", allow_failure=True)
    if head.returncode:
        branch = run_git(root, "symbolic-ref", "--quiet", "HEAD", allow_failure=True)
        if branch.returncode or not branch.stdout.strip().startswith("refs/heads/"):
            raise GitError("Cannot resolve HEAD; repository may be damaged.")
        reference = run_git(root, "show-ref", "--verify", "--quiet", branch.stdout.strip(), allow_failure=True)
        if reference.returncode != 1:
            raise GitError("Cannot read branch history.")
        return {"commit_count": 0, "committer_count": 0, "latest_commit": None, "recent_commits": [], "head": None, "history_scope": "HEAD", "shallow": False}

    # Use a fixed commit so count, people and recent history share one snapshot.
    revision = head.stdout.strip()
    count = int(run_git(root, "rev-list", "--count", revision).stdout.strip())
    fields = run_git(root, "log", "-10", "--format=%H%x00%cN%x00%cI%x00%s%x00", revision).stdout.split("\x00")
    recent = []
    for index in range(0, len(fields) - 1, 4):
        recent.append({"hash": fields[index].strip(), "committer": fields[index + 1], "date": fields[index + 2], "subject": fields[index + 3]})
    people = run_git(root, "log", "--format=%cN%x00%cE%x00", revision).stdout.split("\x00")
    identities = {(people[i].strip(), people[i + 1]) for i in range(0, len(people) - 1, 2)}
    shallow = run_git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"
    return {"commit_count": count, "committer_count": len(identities), "latest_commit": recent[0] if recent else None,
            "recent_commits": recent, "head": revision, "history_scope": "HEAD", "shallow": shallow}
