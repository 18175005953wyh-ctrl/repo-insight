import os
import subprocess
import sys
import tempfile
import unittest
import uuid
import stat
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))


class RepositoryTest(unittest.TestCase):
    def setUp(self):
        # Normal inherited permissions also work in restricted Windows runners.
        self.temporary = Path(tempfile.gettempdir()) / ("repo-insight-test-" + uuid.uuid4().hex)
        self.temporary.mkdir()
        self.addCleanup(self.clean_temporary)
        self.root = self.temporary / "sample repo"
        self.root.mkdir()

    def clean_temporary(self):
        if self.temporary.resolve().parent != Path(tempfile.gettempdir()).resolve() or not self.temporary.name.startswith("repo-insight-test-"):
            raise RuntimeError("Refusing cleanup outside the test temporary directory.")
        for path in sorted(self.temporary.rglob("*"), key=lambda item: len(item.parts), reverse=True):
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.chmod(stat.S_IREAD | stat.S_IWRITE)
                path.unlink()
        self.temporary.rmdir()

    def write(self, name, content=""):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def git(self, *args, person="Example One"):
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        environment.update({"GIT_AUTHOR_NAME": person, "GIT_COMMITTER_NAME": person,
                            "GIT_AUTHOR_EMAIL": person.replace(" ", "").lower() + "@example.invalid",
                            "GIT_COMMITTER_EMAIL": person.replace(" ", "").lower() + "@example.invalid",
                            "GIT_AUTHOR_DATE": "2026-01-01T00:00:00+00:00", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00+00:00"})
        return subprocess.run(["git", "-C", str(self.root), "-c", "commit.gpgsign=false", "-c", "core.hooksPath=nonexistent-test-hooks", *args],
                              env=environment, capture_output=True, text=True, encoding="utf-8", check=True)

    def init(self):
        self.git("init", "-b", "main")

    def commit(self, message="Example commit", person="Example One"):
        self.git("add", ".")
        self.git("commit", "--allow-empty", "-m", message, person=person)
