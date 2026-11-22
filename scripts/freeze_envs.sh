#!/usr/bin/env bash
# Record what is installed in each local Python environment, in the tracked
# lock file next to it. The environments themselves are not in git, so these
# files are the only record of which tool versions produced the published
# benchmark numbers.
#
# Usage (from anywhere in the repository):
#   bash scripts/freeze_envs.sh                        every environment that exists
#   bash scripts/freeze_envs.sh bench/kgtools/.venv    only the named ones
#   bash scripts/freeze_envs.sh --check [env ...]      write nothing; exit 1 when
#                                                      a lock file is out of date
#
# It only reads the environments (a package listing); it installs nothing.
# Needs `uv` on PATH, or `pip` inside the environment.
set -euo pipefail

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$root"

# environment directory : lock file (both relative to the repository root)
pairs=(
  ".venv:requirements.lock.txt"
  "bench/security/.venv:bench/security/requirements.lock.txt"
  "bench/security/finetune/cookbook/training/.venv:bench/security/finetune/requirements-cookbook.lock.txt"
  "bench/test_manipulation/.venv:bench/test_manipulation/requirements.lock.txt"
  "bench/fabrication/.venv:bench/fabrication/requirements-tools.lock.txt"
  "bench/fabrication/.venv-deps:bench/fabrication/requirements-deps.lock.txt"
  "bench/obsolescence/.venv-libs:bench/obsolescence/requirements-libs.lock.txt"
  "bench/kgtools/.venv:bench/kgtools/requirements.lock.txt"
)

check=0
wanted=()
for arg in "$@"; do
  case "$arg" in
    --check) check=1 ;;
    -h|--help) sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) wanted+=("${arg%/}") ;;
  esac
done

# Pins only: comment lines carry the date and are not compared.
pins() { grep -v '^#' "$1" 2>/dev/null || true; }

freeze() {  # $1 = environment directory; prints name==version lines
  local py="$1/bin/python" out err
  err="$(mktemp)"
  if command -v uv >/dev/null 2>&1; then
    # uv prints an informational line on stderr even when all is well, so
    # stderr is kept aside and shown only when the listing fails.
    if ! out="$(uv pip freeze --python "$py" 2>"$err")"; then
      cat "$err" >&2
      rm -f "$err"
      echo "freeze_envs: uv could not list the packages of $1" >&2
      return 1
    fi
  elif "$py" -m pip --version >/dev/null 2>&1; then
    if ! out="$("$py" -m pip freeze --all 2>"$err")"; then
      cat "$err" >&2
      rm -f "$err"
      echo "freeze_envs: pip could not list the packages of $1" >&2
      return 1
    fi
  else
    rm -f "$err"
    echo "freeze_envs: need uv on PATH or pip inside $1" >&2
    return 1
  fi
  rm -f "$err"
  if [ -z "$out" ]; then
    echo "freeze_envs: the listing of $1 is empty; refusing to write an empty lock file" >&2
    return 1
  fi
  # An editable install is printed with this machine's path; keep it relative.
  # The match ignores case because the default macOS file system does.
  printf '%s\n' "$out" | awk -v pre="file://$root/" '
    { at = index(tolower($0), tolower(pre))
      if (at > 0) $0 = substr($0, 1, at - 1) "./" substr($0, at + length(pre))
      print }'
}

status=0
seen=0
for pair in "${pairs[@]}"; do
  env_dir="${pair%%:*}"
  lock="${pair#*:}"
  if [ "${#wanted[@]}" -gt 0 ]; then
    keep=0
    for w in "${wanted[@]}"; do [ "$w" = "$env_dir" ] && keep=1; done
    [ "$keep" -eq 1 ] || continue
  fi
  seen=$((seen + 1))
  if [ ! -x "$env_dir/bin/python" ]; then
    echo "skip     $env_dir (not on this machine; $lock left as it is)"
    continue
  fi
  if ! body="$(freeze "$env_dir")"; then
    echo "freeze_envs: stopped at $env_dir; $lock was not touched" >&2
    exit 1
  fi
  count="$(printf '%s\n' "$body" | grep -c . || true)"
  if [ "$check" -eq 1 ]; then
    if [ "$body" = "$(pins "$lock")" ]; then
      echo "ok       $lock ($count packages)"
    else
      echo "CHANGED  $lock no longer matches $env_dir" >&2
      status=1
    fi
    continue
  fi
  if [ -f "$lock" ] && [ "$body" = "$(pins "$lock")" ]; then
    echo "same     $lock ($count packages)"
    continue
  fi
  py_version="$("$env_dir/bin/python" -c 'import platform; print(platform.python_version())')"
  py_platform="$("$env_dir/bin/python" -c 'import platform; print(platform.system(), platform.machine())')"
  if command -v uv >/dev/null 2>&1; then tool="uv pip freeze ($(uv --version | cut -d' ' -f1,2))"; else tool="pip freeze --all"; fi
  {
    echo "# Python $py_version ($py_platform). Everything installed in $env_dir, frozen $(date '+%Y-%m-%d %H:%M %Z')."
    echo "# Written by scripts/freeze_envs.sh with $tool; $count packages. Do not edit by hand."
    echo "# A record of this machine's environment, not a tested install recipe for another platform."
    # Say which commit an editable (source) install was at.
    printf '%s\n' "$body" | sed -n 's#^-e \(\./.*\)$#\1#p' | while IFS= read -r src; do
      top="$(git -C "$src" rev-parse --show-toplevel 2>/dev/null || true)"
      if [ -n "$top" ] && [ "$top" != "$(git rev-parse --show-toplevel)" ]; then
        # The remote goes into a tracked file: drop any "user:token@" part.
        remote="$(git -C "$src" remote get-url origin 2>/dev/null || echo 'no remote')"
        remote="$(printf '%s' "$remote" | sed -E 's#^([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@]*@#\1#; s#^[^/@:]+@##')"
        echo "# Source install $src: $remote at commit $(git -C "$src" rev-parse HEAD)"
      fi
    done
    printf '%s\n' "$body"
  } > "$lock"
  echo "wrote    $lock ($count packages, Python $py_version)"
done

if [ "$seen" -eq 0 ]; then
  echo "freeze_envs: no known environment matches: ${wanted[*]}" >&2
  exit 2
fi
exit "$status"
