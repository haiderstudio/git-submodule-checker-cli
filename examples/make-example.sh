#!/bin/sh
# Build a small example superproject with one submodule.
# Usage: sh make-example.sh <folder>
# Creates <folder>/sub (the library repo), <folder>/super (the
# superproject, whose submodule is drifted on purpose),
# <folder>/synced (a clone with its submodule checked out at
# the recorded commit), and <folder>/clone (a fresh clone whose
# submodule was never initialised). Commit dates are fixed, so
# the commit SHAs are the same on every run. The caller
# removes the folder.
set -e
DEST="$1"
mkdir -p "$DEST"
cd "$DEST"
export GIT_AUTHOR_NAME="Example Author"
export GIT_AUTHOR_EMAIL="author@example.com"
export GIT_COMMITTER_NAME="Example Author"
export GIT_COMMITTER_EMAIL="author@example.com"
export GIT_AUTHOR_DATE="2026-01-01T00:00:00+00:00"
export GIT_COMMITTER_DATE="2026-01-01T00:00:00+00:00"

git -c init.defaultBranch=main init -q sub
cd sub
echo "version one" > lib.txt
git add lib.txt
git commit -qm "first version of the library"
cd ..

git -c init.defaultBranch=main init -q super
cd super
git -c protocol.file.allow=always submodule add -q ../sub libs/sub
git commit -qm "add library submodule"
cd ..

git clone -q super synced
git -C synced -c protocol.file.allow=always submodule update --init -q

cd super/libs/sub
echo "version two" > lib.txt
git commit -qam "second version of the library"
cd "$DEST"

git clone -q super clone
