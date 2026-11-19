#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  serve) command_name=cao-server ;;
  client) command_name=cao ;;
  *)
    echo "Usage: bash scripts/cao-local.sh {serve|client [cao arguments...]}" >&2
    exit 2
    ;;
esac
shift
if [[ "$command_name" == cao-server && $# -ne 0 ]]; then
  echo "The local CAO server does not accept overrides." >&2
  exit 2
fi

root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
export PATH="$root/.local/bin:$PATH"
if ! tmux_bin="$(type -P tmux)" || ! "$tmux_bin" -V >/dev/null; then
  echo "CAO could not run tmux. Open the workspace Shell and check that 'tmux -V' works." >&2
  exit 1
fi
if ! cao_bin="$(type -P "$command_name")"; then
  echo "Could not find $command_name. See 'Local CAO swarm' in replit.md for setup." >&2
  exit 1
fi
export PATH="$(dirname -- "$tmux_bin"):$PATH"

# CAO startup reconciles persisted sessions against its tmux server. Isolate
# both, and do not let an enclosing tmux pane redirect commands to its socket.
state="$root/.local/state/cao-swarm"
export CAO_HOME_DIR="$state/home"
export TMUX_TMPDIR="$state/tmux"
unset TMUX TMUX_PANE
umask 077
mkdir -p -- "$CAO_HOME_DIR" "$TMUX_TMPDIR"

# Set the environment as well as the flags so CAO and its workers agree on
# the address even when the caller has different CAO defaults.
export CAO_API_HOST=127.0.0.1 CAO_API_PORT=9897
if [[ "$command_name" == cao-server ]]; then
  cd -- "$root"
  exec "$cao_bin" --terminal tmux --host "$CAO_API_HOST" --port "$CAO_API_PORT"
fi
exec "$cao_bin" "$@"
