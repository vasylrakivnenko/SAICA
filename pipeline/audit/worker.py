"""Child process that runs the detectors on one fetched repository.

The detectors parse files that anyone can put in a public repository. A
parser can be made slow or hungry by an input nobody thought of, and a
thread cannot be killed (nor can it be stopped from holding the
interpreter while a regex runs). So for remote audits the whole detection
step runs here, in a process of its own that the parent kills when its
time is up (:func:`pipeline.audit.analyzer.detect_stack_isolated`).

Limits this process puts on itself as well:

* CPU seconds (``RLIMIT_CPU``): the kernel ends it even if the parent died;
* address space (``RLIMIT_AS``) where the kernel enforces it (Linux);
* a watchdog thread that ends the process when its resident memory passes
  the limit (macOS does not enforce ``RLIMIT_AS``; a thread cannot run
  while C code holds the interpreter, which is what the time limit is for);
* no file larger than 1 MB may be written, and no core dump.

Usage: ``python -m pipeline.audit.worker ROOT DATA_DIR MEMORY_BYTES SECONDS``.
Prints the detected stack as JSON on stdout. Exit code 3: memory limit.
"""

from __future__ import annotations

import math
import os
import sys
import threading
import time
from pathlib import Path

EXIT_MEMORY = 3


def _resident_bytes() -> int:
    import resource

    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024  # Linux reports kB


def _address_space_bytes() -> int:
    """Address space this process holds now (Linux); 0 where unknown."""
    try:
        with open("/proc/self/statm", encoding="ascii") as fh:
            return int(fh.read().split()[0]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return 0


def apply_limits(memory_bytes: int, seconds: float) -> None:
    """Best effort: every limit the platform offers; none is required.

    The address-space limit is what the process holds after its imports
    plus ``memory_bytes``, so the interpreter's own size (which differs
    between machines) cannot make every audit fail.
    """
    try:
        import resource
    except ImportError:  # pragma: no cover - not on POSIX
        return
    cpu = int(math.ceil(seconds)) + 1
    address_space = _address_space_bytes() + memory_bytes
    for name, value in (
        ("RLIMIT_CPU", (cpu, cpu + 1)),
        ("RLIMIT_AS", (address_space, address_space)),
        ("RLIMIT_FSIZE", (1_000_000, 1_000_000)),
        ("RLIMIT_CORE", (0, 0)),
    ):
        try:
            resource.setrlimit(getattr(resource, name), value)
        except (AttributeError, ValueError, OSError):
            continue

    def watchdog() -> None:
        while True:
            if _resident_bytes() > memory_bytes:
                os._exit(EXIT_MEMORY)
            time.sleep(0.05)

    threading.Thread(target=watchdog, daemon=True).start()


def main(argv: list[str]) -> int:
    root, data_dir, memory_bytes, seconds = argv
    from pipeline import kg
    from pipeline.audit.analyzer import _build_stack

    apply_limits(int(memory_bytes), float(seconds))
    with kg.use_data_dir(Path(data_dir)):
        stack = _build_stack(Path(root))
    sys.stdout.write(stack.model_dump_json())
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
