# git-submodule-checker-cli

Check git submodules are initialised and checked out at the commit the superproject records, fail CI when one is not.

[![CI](https://github.com/haiderstudio/git-submodule-checker-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/git-submodule-checker-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`git_submodule_checker` reads the submodules a git
superproject records in its index and checks each one
against the working tree: is it initialised, and is the
commit checked out the same commit the superproject
records? It reports each submodule that fails, with its
path and both SHAs, and exits 1, so it can fail a CI run.
A repo whose submodules are all in sync exits 0, and a
repo with no submodules at all exits 0.

- A submodule that drifted from its recorded commit
  builds and tests against the wrong code, and nobody
  notices until a deploy behaves differently from a
  checkout. The fix is one command once it is found
  (`git submodule update`), but nothing stops you
  merging with a drifted submodule. This catches it
  before the merge.
- A fresh clone never initialises its submodules on its
  own — the folders sit there empty until someone runs
  `git submodule update --init`. A CI job that builds
  from a fresh clone without that step silently builds
  without the submodule code at all. This flags the
  empty folder before the build runs.
- It is report-only: it never initialises a submodule,
  never checks anything out, and never commits anything.
  It only runs read-only git commands (`ls-files`,
  `config`, `rev-parse`) in the repo you point it at,
  and it never touches the network — a submodule's
  remote is never contacted, so the check works fully
  offline, on a plane or behind a firewall.
- It also reports two bookkeeping problems: a recorded
  submodule with no entry in `.gitmodules`, and a
  `.gitmodules` entry with no recorded submodule in the
  index. Both are real inconsistencies that break the
  next person who clones the repo.
- More than one repo can be checked in a single run, and
  `--json` prints the result as JSON for a script to
  read.

## Who it is for

Anyone who uses git submodules and does not want a build,
a test run, or a deploy to silently use the wrong code —
teams with a shared library as a submodule, projects
that vendor a dependency this way, and anyone whose CI
clones fresh and needs to know the submodules are
actually there at the right commit.

## What it does NOT do

- It does not check whether a submodule's commits have
  been pushed to its remote. That is push state, and it
  is the job of
  [rodrigo-lima/submodule_checker](https://github.com/rodrigo-lima/submodule_checker)
  (5 stars), a pre-commit hook that compares each
  submodule's local commits against their remotes to
  catch unpushed work at commit time. This repo does
  the other job: whether the working tree is
  initialised at the commit the superproject records,
  as a CI gate. The hook cannot do this job, and this
  tool cannot do the hook's job — use both if you need
  both.
- It does not check for upstream updates to a
  submodule, and it never suggests moving a submodule
  to a newer commit. The recorded commit is the correct
  one by definition; only drift from it is a problem.
- It does not check nested submodules (a submodule
  inside a submodule). Only the superproject's own
  direct submodules are checked.
- It does not initialise, check out, or commit anything.
  It reports, and you fix it with git's own commands.
- It does not need a network connection, and it never
  fetches a URL. A submodule whose remote is down is a
  different problem, and this tool cannot see it.

## How this differs

- A fresh search of GitHub on Nov 13, 2026 found 0
  results for `"git-submodule-checker-cli"` and 8
  results for `git submodule checker`. The only
  established rival is rodrigo-lima/submodule_checker
  (5 stars), and its README, re-read the same day,
  still says its job is comparing each submodule's
  local commits against their remotes to catch
  unpushed work at commit time — push state, not
  drift. It is a pre-commit hook, not a CI gate, and it
  does not check whether the working tree is
  initialised at the commit the superproject records.
  The other results are version checkers and update
  checkers, not drift gates.
- Repo #2, git-branch-cleanup-cli, deletes stale
  branches; repo #65, git-branch-age-checker-cli, flags
  old branches; repo #86, git-signed-commit-checker-cli,
  gates commit signatures — submodule drift is a
  different job on the same repo.

## Install

```sh
git clone https://github.com/haiderstudio/git-submodule-checker-cli.git
cd git-submodule-checker-cli
```

There is nothing else to install: Python 3.10 or newer,
standard library only, no dependencies. Git must be
installed, because git is the tool being checked.

## Usage

Check the repo in the current folder:

```sh
python3 src/git_submodule_checker.py .
```

A repo whose submodules are all in sync passes:

```sh
$ python3 src/git_submodule_checker.py synced
OK — 1 submodule(s) in sync.
```

A repo with a drifted submodule fails, with the path and
both SHAs:

```sh
$ python3 src/git_submodule_checker.py super
FAIL libs/sub: checked-out HEAD e34ce797ad9ea3e012331d2d1702097e74f894f8 differs from recorded commit c41a7332fb48964056eaa00099ba037e48d07965
Checked 1 repo(s), 1 problem(s) in 1 repo(s).
```

A fresh clone whose submodule was never initialised
fails, with the recorded commit:

```sh
$ python3 src/git_submodule_checker.py clone
FAIL libs/sub: uninitialised — recorded commit c41a7332fb48964056eaa00099ba037e48d07965, no checkout found
Checked 1 repo(s), 1 problem(s) in 1 repo(s).
```

A repo with no submodules passes:

```sh
$ python3 src/git_submodule_checker.py /path/to/plain-repo
OK — no submodules recorded.
```

Machine-readable output:

```sh
$ python3 src/git_submodule_checker.py --json super
{
  "repos": [
    {
      "path": "super",
      "submodules": [
        {
          "path": "libs/sub",
          "recorded": "c41a7332fb48964056eaa00099ba037e48d07965",
          "head": "e34ce797ad9ea3e012331d2d1702097e74f894f8",
          "status": "drifted",
          "message": "checked-out HEAD e34ce797ad9ea3e012331d2d1702097e74f894f8 differs from recorded commit c41a7332fb48964056eaa00099ba037e48d07965"
        }
      ],
      "error": null
    }
  ],
  "checked": 1,
  "problems": 1
}
```

Exit codes: 0 when every submodule is in sync (or the
repo has none), 1 when any submodule fails, 2 for a
usage error (a missing folder, a folder that is not a
git repo, or git not installed).

## Examples

A fresh clone is the most common failure — the folders
are there but empty, and the build quietly proceeds
without the library. The bundled example builds a
superproject, a synced clone, and a fresh clone, and
shows all three results. Run every bundled example at
once with `sh examples/run-example.sh` — the output is
saved in
[examples/sample-output.md](examples/sample-output.md),
and `examples/make-example.sh` is the script that
builds the fixture repos (fixed commit dates, so the
SHAs are the same on every run).

A submodule that moved on inside the superproject is
caught with both SHAs on one line, so you can see at a
glance which commit the superproject expects and which
one is actually checked out:

```sh
$ python3 src/git_submodule_checker.py super
FAIL libs/sub: checked-out HEAD e34ce797ad9ea3e012331d2d1702097e74f894f8 differs from recorded commit c41a7332fb48964056eaa00099ba037e48d07965
Checked 1 repo(s), 1 problem(s) in 1 repo(s).
```

Checking more than one repo in one run — a clean repo
and a broken one — reports the broken one and still
counts both:

```sh
$ python3 src/git_submodule_checker.py synced clone
FAIL libs/sub: uninitialised — recorded commit c41a7332fb48964056eaa00099ba037e48d07965, no checkout found
Checked 2 repo(s), 1 problem(s) in 1 repo(s).
```

## How it is tested

```sh
python3 tests/test_git_submodule_checker.py
```

The tests build real git repos in temp folders — a
library repo, a superproject recording it as a
submodule, a synced clone, and a fresh clone — and
cover the check itself (no submodules, all in sync,
drifted HEAD, uninitialised submodule, a submodule
folder deleted, a recorded submodule with no
`.gitmodules` entry, a `.gitmodules` entry with no
recorded submodule, several problems sorted by path,
a missing git binary, a non-repo folder, a missing
folder), the CLI (exit 0/1/2, default path, several
repos in one run, `--json` output, `--version`, a bad
flag, the input repo left unchanged, absolute paths
from another working folder), the bundled examples
(sample output compared byte-for-byte against a fresh
run, the fixture SHAs stable across two builds, and
the README-quoted outputs checked against real runs),
and hygiene checks (no placeholder text, no absolute
paths, no secrets, no network use in the source,
stdlib imports only, `.env` first in `.gitignore`, CI
file runs the test file, and the hygiene scan skips
every `.git` folder anywhere in the tree).

## Contributing

Small, focused improvements are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The
idea of checking submodules is not new — the pre-commit
hook rodrigo-lima/submodule_checker (5 stars) checks
push state, and is named honestly above — but no
existing tool does this one job, the drift check
(initialised plus HEAD equal to the recorded commit),
as a tested command-line CI gate, and every line of
code here is original, built on nothing but Python's
standard library and git itself.
