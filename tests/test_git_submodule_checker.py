#!/usr/bin/env python3
"""Tests for git_submodule_checker — stdlib unittest only.

Every git repo used here is a real repo built in a temp dir:
a library repo, a superproject that records it as a
submodule, a clone with the submodule checked out, and a
fresh clone with the submodule never initialised. No test
reads a path outside its own temp dir, and no test depends
on the current working directory.
"""

import ast
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import git_submodule_checker as checker

REPO = Path(__file__).resolve().parent.parent

FIXED_DATE = "2026-01-01T00:00:00+00:00"


def run_cli(argv):
    """Run main(argv), capture stdout/stderr, return (code, out, err)."""
    out = io.StringIO()
    err = io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            code = checker.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def git(*args, cwd):
    """Run git with fixed identity, return (code, stdout)."""
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "Test Author",
        "GIT_AUTHOR_EMAIL": "author@example.com",
        "GIT_COMMITTER_NAME": "Test Author",
        "GIT_COMMITTER_EMAIL": "author@example.com",
        "GIT_AUTHOR_DATE": FIXED_DATE,
        "GIT_COMMITTER_DATE": FIXED_DATE,
    })
    proc = subprocess.run(
        ["git", "-c", "protocol.file.allow=always"] + list(args),
        cwd=cwd, capture_output=True, text=True, env=env)
    return proc.returncode, proc.stdout


def make_library(root, name="sub"):
    """Create a library repo with one commit, return its HEAD."""
    lib = Path(root) / name
    lib.mkdir()
    code, _ = git("init", "-q", "-b", "main", ".", cwd=str(lib))
    assert code == 0
    (lib / "lib.txt").write_text("version one\n")
    code, _ = git("add", "lib.txt", cwd=str(lib))
    assert code == 0
    code, _ = git("commit", "-qm", "first version", cwd=str(lib))
    assert code == 0
    code, head = git("rev-parse", "HEAD", cwd=str(lib))
    assert code == 0
    return str(lib), head.strip()


def make_super(root, lib_path, name="super"):
    """Create a superproject recording lib_path as libs/sub.

    Returns (super path, recorded SHA). The submodule is
    checked out at the recorded commit.
    """
    sup = Path(root) / name
    sup.mkdir()
    code, _ = git("init", "-q", "-b", "main", ".", cwd=str(sup))
    assert code == 0
    code, _ = git("submodule", "add", "-q", "../sub", "libs/sub",
                  cwd=str(sup))
    assert code == 0, "submodule add failed"
    code, _ = git("commit", "-qm", "add library submodule",
                  cwd=str(sup))
    assert code == 0
    code, sha = git("ls-files", "--stage", "libs/sub", cwd=str(sup))
    assert code == 0
    recorded = sha.split()[1]
    return str(sup), recorded


def drift_submodule(super_path):
    """Commit a new version inside the superproject's submodule.

    Returns the new HEAD. The superproject index still records
    the old commit, so the submodule is now drifted.
    """
    sub = Path(super_path) / "libs" / "sub"
    (sub / "lib.txt").write_text("version two\n")
    code, _ = git("commit", "-qam", "second version", cwd=str(sub))
    assert code == 0
    code, head = git("rev-parse", "HEAD", cwd=str(sub))
    assert code == 0
    return head.strip()


def clone_repo(root, source, name):
    """Clone source into root/name without initialising submodules."""
    code, _ = git("clone", "-q", source, name, cwd=root)
    assert code == 0
    return str(Path(root) / name)


class FixtureMixin(unittest.TestCase):
    """A temp dir holding a library and a superproject."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.lib, self.lib_head = make_library(self.root)
        self.super, self.recorded = make_super(self.root, self.lib)

    def tearDown(self):
        self.tmp.cleanup()


class TestCheckRepo(FixtureMixin):
    def test_no_submodules_is_ok(self):
        plain = Path(self.root) / "plain"
        plain.mkdir()
        code, _ = git("init", "-q", "-b", "main", ".", cwd=str(plain))
        assert code == 0
        problems, error = checker.check_repo(str(plain))
        self.assertIsNone(error)
        self.assertEqual(problems, [])

    def test_all_in_sync(self):
        problems, error = checker.check_repo(self.super)
        self.assertIsNone(error)
        self.assertEqual(problems, [])

    def test_drifted_submodule(self):
        new_head = drift_submodule(self.super)
        problems, error = checker.check_repo(self.super)
        self.assertIsNone(error)
        self.assertEqual(len(problems), 1)
        problem = problems[0]
        self.assertEqual(problem["status"], "drifted")
        self.assertEqual(problem["path"], "libs/sub")
        self.assertEqual(problem["recorded"], self.recorded)
        self.assertEqual(problem["head"], new_head)
        self.assertNotEqual(new_head, self.recorded)

    def test_uninitialised_submodule(self):
        clone = clone_repo(self.root, self.super, "clone")
        problems, error = checker.check_repo(clone)
        self.assertIsNone(error)
        self.assertEqual(len(problems), 1)
        problem = problems[0]
        self.assertEqual(problem["status"], "uninitialised")
        self.assertEqual(problem["path"], "libs/sub")
        self.assertEqual(problem["recorded"], self.recorded)
        self.assertIsNone(problem["head"])

    def test_uninitialised_reports_recorded_not_super_head(self):
        # A fresh clone's submodule folder sits inside a repo, so
        # a naive `git rev-parse HEAD` there answers with the
        # SUPERPROJECT's HEAD. The report must not do that: the
        # recorded SHA is the library's commit, never the
        # superproject's.
        clone = clone_repo(self.root, self.super, "clone")
        code, super_head = git("rev-parse", "HEAD", cwd=clone)
        assert code == 0
        problems, _error = checker.check_repo(clone)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["status"], "uninitialised")
        self.assertNotEqual(problems[0]["recorded"],
                            super_head.strip())

    def test_submodule_folder_deleted_is_uninitialised(self):
        import shutil
        shutil.rmtree(Path(self.super) / "libs" / "sub")
        problems, error = checker.check_repo(self.super)
        self.assertIsNone(error)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["status"], "uninitialised")

    def test_no_gitmodules_entry(self):
        # A gitlink in the index with no .gitmodules entry: add
        # the link straight to the index, no .gitmodules at all.
        plain = Path(self.root) / "plain"
        plain.mkdir()
        code, _ = git("init", "-q", "-b", "main", ".", cwd=str(plain))
        assert code == 0
        code, _ = git("update-index", "--add", "--cacheinfo",
                      "160000,%s,libs/extra" % self.lib_head,
                      cwd=str(plain))
        assert code == 0
        problems, error = checker.check_repo(str(plain))
        self.assertIsNone(error)
        statuses = [p["status"] for p in problems]
        self.assertIn("no-gitmodules-entry", statuses)
        entry = [p for p in problems
                 if p["status"] == "no-gitmodules-entry"][0]
        self.assertEqual(entry["path"], "libs/extra")
        self.assertEqual(entry["recorded"], self.lib_head)

    def test_gitmodules_entry_with_no_gitlink(self):
        (Path(self.super) / ".gitmodules").write_text(
            '[submodule "libs/sub"]\n\tpath = libs/sub\n'
            '\turl = ../sub\n'
            '[submodule "libs/stale"]\n\tpath = libs/stale\n'
            '\turl = ../missing\n')
        code, _ = git("add", ".gitmodules", cwd=self.super)
        assert code == 0
        code, _ = git("commit", "-qm", "add a stale entry",
                      cwd=self.super)
        assert code == 0
        problems, error = checker.check_repo(self.super)
        self.assertIsNone(error)
        stale = [p for p in problems
                 if p["path"] == "libs/stale"]
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0]["status"], "not-recorded")
        self.assertEqual(
            [p for p in problems if p["path"] == "libs/sub"], [])

    def test_non_repo_directory(self):
        plain = Path(self.root) / "not-a-repo"
        plain.mkdir()
        problems, error = checker.check_repo(str(plain))
        self.assertEqual(problems, [])
        self.assertIn("not a git repository", error)

    def test_missing_directory(self):
        missing = str(Path(self.root) / "no-such-dir")
        problems, error = checker.check_repo(missing)
        self.assertEqual(problems, [])
        self.assertIn("no such directory", error)

    def test_missing_git_binary(self):
        with mock.patch("shutil.which", return_value=None):
            problems, error = checker.check_repo(self.super)
        self.assertEqual(problems, [])
        self.assertIn("git is not installed", error)

    def test_multiple_problems_sorted_by_path(self):
        drift_submodule(self.super)
        second_lib, _head = make_library(self.root, name="sub2")
        code, _ = git("submodule", "add", "-q", "../sub2",
                      "libs/aaa", cwd=self.super)
        assert code == 0
        code, _ = git("commit", "-qm", "add second submodule",
                      cwd=self.super)
        assert code == 0
        import shutil
        shutil.rmtree(Path(self.super) / "libs" / "aaa")
        problems, error = checker.check_repo(self.super)
        self.assertIsNone(error)
        self.assertEqual(
            [p["path"] for p in problems],
            ["libs/aaa", "libs/sub"])
        self.assertEqual(problems[0]["status"], "uninitialised")
        self.assertEqual(problems[1]["status"], "drifted")


class TestRunCli(FixtureMixin):
    def test_synced_repo_exits_zero(self):
        code, out, err = run_cli([self.super])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")
        self.assertIn("OK — 1 submodule(s) in sync.", out)

    def test_no_submodules_exits_zero(self):
        plain = Path(self.root) / "plain"
        plain.mkdir()
        code, _ = git("init", "-q", "-b", "main", ".", cwd=str(plain))
        assert code == 0
        code, out, _err = run_cli([str(plain)])
        self.assertEqual(code, 0)
        self.assertIn("OK — no submodules recorded.", out)

    def test_drifted_repo_exits_one(self):
        new_head = drift_submodule(self.super)
        code, out, _err = run_cli([self.super])
        self.assertEqual(code, 1)
        self.assertIn(
            "FAIL libs/sub: checked-out HEAD %s differs from "
            "recorded commit %s" % (new_head, self.recorded), out)
        self.assertIn("Checked 1 repo(s), 1 problem(s) in 1 repo(s).",
                      out)

    def test_uninitialised_repo_exits_one(self):
        clone = clone_repo(self.root, self.super, "clone")
        code, out, _err = run_cli([clone])
        self.assertEqual(code, 1)
        self.assertIn(
            "FAIL libs/sub: uninitialised — recorded commit %s, "
            "no checkout found" % self.recorded, out)

    def test_default_path_is_current_directory(self):
        old = os.getcwd()
        os.chdir(self.super)
        try:
            code, out, _err = run_cli([])
        finally:
            os.chdir(old)
        self.assertEqual(code, 0)
        self.assertIn("OK — 1 submodule(s) in sync.", out)

    def test_multiple_repos(self):
        clone = clone_repo(self.root, self.super, "clone")
        code, out, _err = run_cli([self.super, clone])
        self.assertEqual(code, 1)
        self.assertIn("Checked 2 repo(s), 1 problem(s) in 1 repo(s).",
                      out)

    def test_non_repo_exits_two(self):
        plain = Path(self.root) / "not-a-repo"
        plain.mkdir()
        code, _out, err = run_cli([str(plain)])
        self.assertEqual(code, 2)
        self.assertIn("not a git repository", err)

    def test_missing_path_exits_two(self):
        code, _out, err = run_cli([str(Path(self.root) / "gone")])
        self.assertEqual(code, 2)
        self.assertIn("no such directory", err)

    def test_bad_flag_exits_two(self):
        code, _out, _err = run_cli(["--nope"])
        self.assertEqual(code, 2)

    def test_version_flag(self):
        code, out, _err = run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("git_submodule_checker 1.0.0", out)

    def test_json_output(self):
        new_head = drift_submodule(self.super)
        code, out, _err = run_cli(["--json", self.super])
        self.assertEqual(code, 1)
        data = json.loads(out)
        self.assertEqual(data["checked"], 1)
        self.assertEqual(data["problems"], 1)
        self.assertEqual(data["repos"][0]["path"], self.super)
        sub = data["repos"][0]["submodules"][0]
        self.assertEqual(sub["path"], "libs/sub")
        self.assertEqual(sub["status"], "drifted")
        self.assertEqual(sub["recorded"], self.recorded)
        self.assertEqual(sub["head"], new_head)

    def test_json_output_when_ok(self):
        code, out, _err = run_cli(["--json", self.super])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["problems"], 0)
        self.assertEqual(data["repos"][0]["submodules"], [])

    def test_input_repo_is_left_unchanged(self):
        before = subprocess.run(
            ["git", "status", "--porcelain"], cwd=self.super,
            capture_output=True, text=True).stdout
        run_cli([self.super])
        run_cli(["--json", self.super])
        after = subprocess.run(
            ["git", "status", "--porcelain"], cwd=self.super,
            capture_output=True, text=True).stdout
        self.assertEqual(before, after)

    def test_absolute_paths_work_from_other_cwd(self):
        # The CLI takes absolute paths, so it must work from
        # anywhere — this is the csv-quote lesson: a test that
        # only passes from the repo root is not a passing test.
        code, out, _err = run_cli([self.super])
        self.assertEqual(code, 0)
        self.assertIn("OK — 1 submodule(s) in sync.", out)


class TestExamples(unittest.TestCase):
    def test_run_example_output_matches_sample(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            cwd=REPO, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        expected = (REPO / "examples/sample-output.md").read_text()
        self.assertEqual(result.stdout, expected)

    def test_make_example_is_deterministic(self):
        # Two fresh fixtures must produce the same SHAs, or the
        # sample output could not be trusted.
        outs = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(
                    ["sh", "examples/make-example.sh", tmp],
                    cwd=REPO, capture_output=True, text=True,
                    check=True)
                code, head = git("rev-parse", "HEAD",
                                 cwd=str(Path(tmp) / "super"
                                         / "libs" / "sub"))
                assert code == 0
                outs.append(head.strip())
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0],
                         "e34ce797ad9ea3e012331d2d1702097e74f894f8")

    def test_readme_quotes_match_real_runs(self):
        readme = (REPO / "README.md").read_text()
        script = str(REPO / "src/git_submodule_checker.py")
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(
                ["sh", "examples/make-example.sh", tmp],
                cwd=REPO, capture_output=True, text=True,
                check=True)
            synced = subprocess.run(
                [sys.executable, script, "synced"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(synced.returncode, 0)
            self.assertIn(synced.stdout.strip(), readme)
            drifted = subprocess.run(
                [sys.executable, script, "super"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(drifted.returncode, 1)
            self.assertIn(drifted.stdout.strip(), readme)
            clone = subprocess.run(
                [sys.executable, script, "clone"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(clone.returncode, 1)
            self.assertIn(clone.stdout.strip(), readme)
            js = subprocess.run(
                [sys.executable, script, "--json", "super"],
                cwd=tmp, capture_output=True, text=True)
            self.assertEqual(js.returncode, 1)
            self.assertIn(js.stdout.strip(), readme)


class TestHygiene(unittest.TestCase):
    def _repo_files(self):
        for root, dirs, files in os.walk(REPO):
            # Skip every .git directory anywhere in the tree:
            # GitHub ships sample hooks under .git/hooks, and
            # the example fixtures may carry .git folders too.
            dirs[:] = [d for d in dirs
                       if d not in (".git", "__pycache__", "tests")]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                yield Path(root) / name

    def test_no_placeholder_text(self):
        banned = ["TODO", "coming soon", "lorem", "FIXME", "XXX"]
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for word in banned:
                if word in text:
                    hits.append("%s: %s" % (path.name, word))
        self.assertEqual(hits, [])

    def test_no_absolute_paths(self):
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore")
            for marker in ("/home/", "/Users/", "C:\\"):
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_no_secrets(self):
        hits = []
        for path in self._repo_files():
            text = path.read_text(errors="ignore").lower()
            for marker in ("api_key", "api-key", "password", "secret=",
                           "token="):
                if marker in text:
                    hits.append("%s: %s" % (path.name, marker))
        self.assertEqual(hits, [])

    def test_stdlib_imports_only(self):
        stdlib = set(sys.stdlib_module_names)
        for target in (REPO / "src/git_submodule_checker.py",
                       REPO / "tests/test_git_submodule_checker.py"):
            tree = ast.parse(target.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            self.assertFalse(
                imported - stdlib - {"git_submodule_checker"},
                (target.name, imported))
            self.assertNotIn("yaml", imported)

    def test_no_network_use_in_src(self):
        src = (REPO / "src/git_submodule_checker.py").read_text()
        for marker in ("urllib", "requests", "socket", "http.client",
                       "urlopen", "urlretrieve"):
            self.assertNotIn(marker, src, marker)

    def test_gitignore_lists_env_first(self):
        lines = (REPO / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_ci_runs_this_test_file(self):
        ci = (REPO / ".github/workflows/ci.yml").read_text()
        self.assertIn("tests/test_git_submodule_checker.py", ci)
        self.assertIn("ubuntu-latest", ci)
        self.assertIn("3.12", ci)
        self.assertIn("actions/checkout", ci)
        self.assertIn("setup-python", ci)
        self.assertIn("push", ci)
        self.assertIn("pull_request", ci)

    def test_hygiene_scan_skips_git_dirs_anywhere(self):
        # The scan above must skip a .git folder nested deep in
        # the tree, or a fixture .git would fail it on CI.
        nested = REPO / "examples" / "fake-fixture" / ".git" / "hooks"
        nested.mkdir(parents=True, exist_ok=True)
        try:
            (nested / "sample").write_text("# TODO: sample hook\n")
            seen = [p for p in self._repo_files()
                    if p.name == "sample"]
            self.assertEqual(seen, [])
        finally:
            import shutil
            shutil.rmtree(REPO / "examples" / "fake-fixture")


if __name__ == "__main__":
    unittest.main()
