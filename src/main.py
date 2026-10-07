"""Command-line entry point for Repo Insight."""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

from git_analyzer import GitError, analyze_git, analyze_git_history, repository_root
from report_generator import write_reports
from scanner import scan_repository


def positive_integer(value: str) -> int:
    try:
        number = int(value) if value.isascii() and value.isdecimal() else 0
    except ValueError:
        number = 0
    if number <= 0:
        raise argparse.ArgumentTypeError("git-limit must be a positive integer.")
    return number


def format_activity_summary(activity: dict) -> str:
    buckets = activity["buckets"]
    if not buckets:
        return "No Git activity in this history window."
    lines = [f"Git Activity Trend ({activity['period']}, {activity['timezone']}; latest {min(8, len(buckets))} of {len(buckets)} buckets):"]
    for bucket in buckets[-8:]:
        lines.append(f"{bucket['period_start']}  commits={bucket['commit_count']}  files={bucket['files_changed']}  "
                     f"+{bucket['additions']}/-{bucket['deletions']}  churn={bucket['churn']}  binary={bucket['binary_changes']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze a local Git repository and generate JSON/HTML reports.")
    parser.add_argument("target", type=Path, help="Repository directory or a directory inside it")
    parser.add_argument("--output", type=Path, default=Path("reports"), help="Report directory (default: ./reports)")
    parser.add_argument("--git-limit", type=positive_integer, default=100, help="Maximum commits for hotspots and activity (default: 100; not number of files or buckets)")
    parser.add_argument("--trend-period", choices=("day", "week", "month"), default="week", help="UTC activity bucket period (default: week; weeks start Monday)")
    args = parser.parse_args(argv)
    try:
        target = args.target.expanduser().resolve()
        if not target.exists():
            raise ValueError("Target path does not exist.")
        if not target.is_dir():
            raise ValueError("Target path is not a directory.")
        root = repository_root(target)
        output = args.output.expanduser().resolve()
        if root == output or root.is_relative_to(output):
            raise ValueError("Output must be a separate directory, not the repository root or its ancestor.")
        if any(part.lower() == ".git" for part in output.parts):
            raise ValueError("Output cannot be inside .git metadata.")
        git = analyze_git(root)
        history = analyze_git_history(root, git, args.git_limit, args.trend_period)
        scan = scan_repository(root, (output,))
        data = {"schema_version": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
                "repository_name": root.name, "repository_path": str(root), "git": git, "scan": scan, "git_history": history}
        write_reports(data, output)
    except (ValueError, OSError, GitError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"Repository: {root}")
    print(f"Files: {scan['file_count']} | Directories: {scan['directory_count']} | Non-empty text lines: {scan['nonempty_lines']}")
    print(f"Commits: {git['commit_count']} | Committers: {git['committer_count']} | Markers: {sum(scan['marker_counts'].values())}")
    print(f"Skipped text files: {len(scan['skipped_text'])} | Warnings: {len(scan['warnings'])}")
    print(f"Top Git Hotspots ({history['analyzed_commits']} commits analyzed; limit {history['requested_limit']}):")
    for index, item in enumerate(history["hotspots"], 1):
        print(f"{index}. {item['path']!r}  {item['commit_count']} commits  +{item['additions']}/-{item['deletions']}  churn={item['churn']}")
    if not history["hotspots"]:
        print("No numeric file hotspots in this history window.")
    print(format_activity_summary(history["activity"]))
    for warning in history["warnings"]:
        print(f"Git history warning: {warning}", file=sys.stderr)
    print(f"JSON: {output / 'report.json'}\nHTML: {output / 'report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
