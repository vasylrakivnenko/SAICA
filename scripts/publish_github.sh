#!/usr/bin/env bash
# Publish `main` to GitHub without the folders that are not public yet.
#
#   bash scripts/publish_github.sh            build the branch `public` and show what a push would send
#   bash scripts/publish_github.sh --push     the same, then push it to origin main
#
# `main` on this machine keeps everything. The branch `public` is rebuilt from it each time: the commits of
# `main` after BASE, with every path in EXCLUDE taken out. bench/ and the two reports do not exist on GitHub;
# research/ stays exactly as it was at BASE. The rewrite keeps authors, dates and messages, so commits published earlier
# come out with the same ids and a later run only adds the new ones (a fast-forward push).
#
# Never run `git push origin main`: GitHub refuses it anyway, because the two histories differ after BASE.
# To publish a folder later, take it out of EXCLUDE; that changes the ids after BASE, so the next push has to
# be forced once (`git push --force-with-lease origin public:main`), and that is your decision to make.
set -euo pipefail

BASE=537ec698050fb384be71343fd4aeb0a970dc9d97   # last commit that GitHub and local main have in common
# Not public yet: the benchmark harness and per-sample tables, the working notes, and the two internal reports
# of November 2026 (they describe weaknesses, the security review of the backend and the hosting setup).
EXCLUDE=(bench research REWIEW_NOV_21.md FIXES_NOV_21.md)
KEEP_AS_AT_BASE=(research)                       # of those, the ones GitHub already has: left as they are there

cd "$(git rev-parse --show-toplevel)"
git merge-base --is-ancestor "$BASE" main || { echo "BASE is not an ancestor of main" >&2; exit 1; }

# The rewrite runs in a throw-away worktree, so uncommitted changes in this one are neither needed nor touched.
# Only what is committed on main is published.
work="$(mktemp -d)"
trap 'git worktree remove --force "$work" >/dev/null 2>&1 || true; rm -rf "$work"' EXIT
git worktree add --quiet --detach "$work" main

restore=""
for p in "${KEEP_AS_AT_BASE[@]}"; do restore+=" && git read-tree --prefix=$p/ $BASE:$p"; done
git branch -f public main >/dev/null
FILTER_BRANCH_SQUELCH_WARNING=1 git -C "$work" filter-branch -f --prune-empty \
  --index-filter "git rm -r -q --cached --ignore-unmatch ${EXCLUDE[*]}$restore" \
  -- "$BASE..public" >/dev/null
git update-ref -d refs/original/refs/heads/public 2>/dev/null || true

# Refuse to go on if an excluded path changed anywhere in the rewritten commits.
leaked="$(git log --format= --name-only "$BASE..public" -- "${EXCLUDE[@]}" | sort -u)"
if [ -n "$leaked" ]; then
  echo "Excluded paths are still touched by the rewritten commits:" >&2
  echo "$leaked" | head -20 >&2
  exit 1
fi

git fetch --quiet origin main
echo "public: $(git rev-list --count "$BASE..public") commits after BASE; $(git rev-list --count origin/main..public) not on GitHub yet"
if ! git merge-base --is-ancestor origin/main public; then
  echo "origin/main is not an ancestor of public: someone pushed, or EXCLUDE changed. Nothing pushed." >&2
  exit 1
fi
if [ "${1:-}" = "--push" ]; then
  git push origin public:main
else
  echo "Dry run. To publish: bash scripts/publish_github.sh --push"
fi
