#!/usr/bin/env python3
"""Check git submodules are initialised at the recorded commit.

Run: python3 src/git_submodule_checker.py .
     python3 src/git_submodule_checker.py /path/to/repo
     python3 src/git_submodule_checker.py --json .

A submodule that drifted from its recorded commit builds and
tests against the wrong code, and nobody notices until a
deploy behaves differently from a checkout. This tool checks
every submodule the superproject records and reports each
one that is uninitialised, or whose checked-out HEAD differs
from the commit the superproject records, with its path and
both SHAs. It exits 1 when any submodule fails, so it can
fail a CI run. A repo whose submodules are all in sync
exits 0, and a repo with no submodules at all exits 0.

The check is read-only: it never initialises a submodule,
never checks anything out, and never commits anything. It
only runs read-only git commands (ls-files, config, and
rev-parse) in the repo you point it at, and it never
touches the network — a submodule's remote is never
contacted, so this works fully offline.

It also reports two bookkeeping problems: a recorded
submodule with no entry in .gitmodules, and a .gitmodules
entry with no recorded submodule in the index. Nested
submodules (a submodule inside a submodule) are not
checked.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

__version__ = "1.0.0"

GITLINK_MODE = "160000"


def _git_executable():
    """Return the git binary path, or None when git is missing."""
    return shutil.which("git")


def _run_git(args, cwd):
    """Run a git command, return (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True,
            text=True, timeout=60)
    except FileNotFoundError:
        return 127, "", "git not found"
    except subprocess.TimeoutExpired:
        return 124, "", "git command timed out"
    return proc.returncode, proc.stdout, proc.stderr


def _is_repo(path):
    """True when path is the top of a git working tree."""
    code, _out, _err = _run_git(["rev-parse", "--git-dir"], path)
    return code == 0


def _recorded_submodules(path):
    """Return {submodule path: recorded SHA} from the index.

    Every gitlink entry (mode 160000) in `git ls-files --stage`
    is a submodule the superproject records, with the commit it
    expects checked out.
    """
    code, out, _err = _run_git(["ls-files", "--stage"], path)
    if code != 0:
        return None
    recorded = {}
    for line in out.splitlines():
        if "\t" not in line:
            continue
        meta, sub_path = line.split("\t", 1)
        parts = meta.split()
        if len(parts) >= 2 and parts[0] == GITLINK_MODE:
            recorded[sub_path] = parts[1]
    return recorded


def _gitmodules_paths(path):
    """Return the set of submodule paths listed in .gitmodules.

    An empty set means there is no .gitmodules file, or it
    lists nothing. A missing file is not an error on its own.
    """
    code, out, _err = _run_git(
        ["config", "-f", ".gitmodules", "--get-regexp",
         r"^submodule\..*\.path$"], path)
    if code != 0:
        return set()
    found = set()
    for line in out.splitlines():
        if " " in line:
            _key, value = line.split(" ", 1)
            found.add(value.strip())
    return found


def _checked_out_head(repo, sub_path):
    """Return the submodule's checked-out HEAD SHA, or None.

    None means the submodule is not initialised: the folder is
    missing, empty, or not a git checkout, or HEAD cannot be
    read. The caller reports that as uninitialised.
    """
    target = os.path.join(repo, sub_path)
    if not os.path.isdir(target):
        return None
    # A submodule checkout always carries its own .git (a file
    # pointing at the superproject's .git/modules entry, or a
    # directory). Without it, the folder is not a checkout at
    # all — and rev-parse would silently walk up and answer
    # with the SUPERPROJECT's HEAD, which is exactly the wrong
    # answer here.
    if not os.path.exists(os.path.join(target, ".git")):
        return None
    code, out, _err = _run_git(["rev-parse", "HEAD"], target)
    if code != 0:
        return None
    head = out.strip()
    return head or None


def check_repo(path):
    """Check one repo. Returns (problems, error).

    Each problem is {"path": str, "recorded": str or None,
    "head": str or None, "status": str, "message": str}.
    "status" is one of "uninitialised", "drifted",
    "no-gitmodules-entry", or "not-recorded". "error" is None
    unless the repo cannot be checked at all.
    """
    if _git_executable() is None:
        return [], "git is not installed or not on PATH"
    if not os.path.isdir(path):
        return [], "no such directory: %s" % path
    if not _is_repo(path):
        return [], "not a git repository: %s" % path
    recorded = _recorded_submodules(path)
    if recorded is None:
        return [], "could not read the git index in: %s" % path
    listed = _gitmodules_paths(path)
    problems = []
    for sub_path in sorted(recorded):
        sha = recorded[sub_path]
        if sub_path not in listed:
            problems.append({
                "path": sub_path, "recorded": sha, "head": None,
                "status": "no-gitmodules-entry",
                "message": "no entry in .gitmodules",
            })
        head = _checked_out_head(path, sub_path)
        if head is None:
            problems.append({
                "path": sub_path, "recorded": sha, "head": None,
                "status": "uninitialised",
                "message": "uninitialised — no checkout found",
            })
        elif head != sha:
            problems.append({
                "path": sub_path, "recorded": sha, "head": head,
                "status": "drifted",
                "message": "checked-out HEAD %s differs from "
                           "recorded commit %s" % (head, sha),
            })
    for sub_path in sorted(listed - set(recorded)):
        problems.append({
            "path": sub_path, "recorded": None, "head": None,
            "status": "not-recorded",
            "message": "listed in .gitmodules but not recorded "
                       "in the index",
        })
    return problems, None


def format_problem(path, problem):
    """One human-readable line for one failing submodule."""
    if problem["status"] == "drifted":
        return ("FAIL %s: checked-out HEAD %s differs from "
                "recorded commit %s"
                % (problem["path"], problem["head"],
                   problem["recorded"]))
    if problem["status"] == "uninitialised":
        return ("FAIL %s: uninitialised — recorded commit %s, "
                "no checkout found"
                % (problem["path"], problem["recorded"]))
    if problem["status"] == "no-gitmodules-entry":
        return ("FAIL %s: no entry in .gitmodules — recorded "
                "commit %s" % (problem["path"], problem["recorded"]))
    return "FAIL %s: %s" % (problem["path"], problem["message"])


def run(paths, as_json=False):
    """Check repos, print the report, return the exit code."""
    results = []
    problems = 0
    repos_with_problems = 0
    for path in paths:
        bad, error = check_repo(path)
        if error:
            print("error: %s" % error, file=sys.stderr)
            return 2
        count = len(bad)
        if count:
            problems += count
            repos_with_problems += 1
        results.append({"path": path, "submodules": bad,
                        "error": None})
    if as_json:
        print(json.dumps(
            {"repos": results, "checked": len(paths),
             "problems": problems},
            indent=2))
    else:
        for result in results:
            for problem in result["submodules"]:
                print(format_problem(result["path"], problem))
        if problems:
            print("Checked %d repo(s), %d problem(s) in %d repo(s)."
                  % (len(paths), problems, repos_with_problems))
        else:
            total = sum(
                len(_recorded_submodules(p) or {})
                for p in paths)
            if total:
                print("OK — %d submodule(s) in sync." % total)
            else:
                print("OK — no submodules recorded.")
    return 1 if problems else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="git_submodule_checker",
        description="Check git submodules are initialised and "
                    "checked out at the commit the superproject "
                    "records, fail CI when one is not.")
    parser.add_argument("paths", nargs="*", default=["."],
                        help="repo folders to check (default: .)")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON")
    parser.add_argument("--version", action="version",
                        version="%(prog)s " + __version__)
    args = parser.parse_args(argv)
    return run(args.paths, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
