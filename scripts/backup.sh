#!/usr/bin/env bash
# Back up everything that exists only on this machine, in one command.
#
# Usage:
#   bash scripts/backup.sh <destination-dir>            e.g. a folder on another disk
#   bash scripts/backup.sh <destination-dir> --dry-run  list what would be written, with sizes
#
# It writes a new folder <destination-dir>/saica-backup-<date>-<time>/ with:
#   repo.bundle                 every branch and tag of the git repository
#                               (restore: git clone repo.bundle saica)
#   worktree-uncommitted.tar.gz files that are changed or new and not committed
#                               (git-ignored files are left out)
#   bench-<mode>-<folder>.tar.gz  one archive per bench/<mode>/data, results and
#                               results_backup_* folder: the datasets and the raw
#                               model answers, which are not in git
#   research-backups.tar.gz     research/backups/ (database dumps), if present
#   SHA256SUMS                  checksums of all of the above
#                               (verify: shasum -a 256 -c SHA256SUMS)
#
# Not copied: .env files and other secrets, virtual environments (their
# contents are recorded in the requirements*.lock.txt files), node_modules,
# caches, bench/_snapshots.
#
# The script only reads the repository. It does not push or upload anything;
# the destination is wherever you point it.
set -euo pipefail

dest="${1:-}"
dry=0
[ "${2:-}" = "--dry-run" ] && dry=1
if [ -z "$dest" ] || [ "$dest" = "-h" ] || [ "$dest" = "--help" ]; then
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"

if [ ! -d "$dest" ]; then
  echo "backup: destination folder does not exist: $dest" >&2
  exit 2
fi
dest_abs="$(cd -- "$dest" && pwd -P)"
# Compare without case: the default macOS file system ignores it.
lower() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]'; }
case "$(lower "$dest_abs")/" in
  "$(lower "$root")"/*)
    echo "backup: the destination must be outside the repository ($root)" >&2
    exit 2 ;;
esac

if command -v shasum >/dev/null 2>&1; then sum() { shasum -a 256 "$@"; }
else sum() { sha256sum "$@"; }; fi

out="$dest_abs/saica-backup-$(date '+%Y%m%d-%H%M%S')"

# Folders that are not in git and cannot be rebuilt from it. (The loops below
# write ${data_dirs[@]+...}: bash 3.2, the macOS default, treats an empty
# array as unset under `set -u`.)
data_dirs=()
for d in bench/*/data bench/*/results bench/*/results_backup_*; do
  [ -d "$d" ] && data_dirs+=("$d")
done

# Changed and new files (never ignored ones, so never .env).
uncommitted="$(mktemp)"
trap 'rm -f "$uncommitted"' EXIT
git ls-files -z --modified --others --exclude-standard | sort -zu > "$uncommitted"
n_uncommitted="$(tr -cd '\0' < "$uncommitted" | wc -c | tr -d ' ')"

if [ "$dry" -eq 1 ]; then
  echo "Would write to: $out"
  echo "  repo.bundle                   $(git for-each-ref --format='%(refname)' refs/heads refs/tags | wc -l | tr -d ' ') branches and tags, $(git rev-list --all --count) commits"
  echo "  worktree-uncommitted.tar.gz   $n_uncommitted changed or new files"
  for d in ${data_dirs[@]+"${data_dirs[@]}"}; do
    name="$(printf '%s' "$d" | tr '/' '-').tar.gz"
    printf '  %-45s %s\n' "$name" "$(du -sh "$d" | cut -f1)"
  done
  [ -d research/backups ] && echo "  research-backups.tar.gz       $(du -sh research/backups | cut -f1)"
  echo "Nothing was written (dry run)."
  exit 0
fi

mkdir "$out"
echo "Writing to $out"

git bundle create "$out/repo.bundle" --all
git bundle verify "$out/repo.bundle" >/dev/null
echo "  repo.bundle"

if [ "$n_uncommitted" -gt 0 ]; then
  # Files deleted in the working tree are listed by git but are not there to copy.
  existing="$(mktemp)"
  while IFS= read -r -d '' f; do
    [ -e "$f" ] && printf '%s\0' "$f"
  done < "$uncommitted" > "$existing"
  tar -czf "$out/worktree-uncommitted.tar.gz" --null -T "$existing"
  rm -f "$existing"
  echo "  worktree-uncommitted.tar.gz ($n_uncommitted files listed)"
fi

for d in ${data_dirs[@]+"${data_dirs[@]}"}; do
  name="$(printf '%s' "$d" | tr '/' '-').tar.gz"
  tar -czf "$out/$name" "$d"
  echo "  $name"
done

if [ -d research/backups ]; then
  tar -czf "$out/research-backups.tar.gz" research/backups
  echo "  research-backups.tar.gz"
fi

(
  cd "$out"
  # A clean repository with no bench data has no archive: list what is there.
  files=(repo.bundle)
  for f in *.tar.gz; do
    [ -e "$f" ] && files+=("$f")
  done
  sum -- "${files[@]}" > SHA256SUMS
)
echo "  SHA256SUMS ($(wc -l < "$out/SHA256SUMS" | tr -d ' ') files)"
echo "Done: $(du -sh "$out" | cut -f1) in $out"
echo "Check a copy with: cd \"$out\" && shasum -a 256 -c SHA256SUMS"
