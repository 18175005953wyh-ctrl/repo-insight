"""Read local Git history. Never fetch, push, or modify repository configuration."""

import os
import subprocess
from pathlib import Path


class GitError(Exception):
    pass


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
