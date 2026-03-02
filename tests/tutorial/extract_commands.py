#!/usr/bin/env python3
"""
Extract shell code blocks from MyST Markdown tutorial files.

Usage
-----
    python3 tests/tutorial/extract_commands.py docs/tutorial/environment.md \
        tests/tutorial/01_environment.sh

    # Print to stdout (no output file argument)
    python3 tests/tutorial/extract_commands.py docs/tutorial/environment.md

What gets extracted
-------------------
Only fenced code blocks whose opening fence is exactly:

    ```shell

Any other language tag (``bash``, ``text``, ``console``, etc.) is ignored.

Skipping a block
----------------
Add ``<!-- test:skip -->`` on the line immediately before the opening fence
(blank lines between the marker and the fence are allowed):

    <!-- test:skip -->
    ```shell
    watch juju status --color   ← long-running; skip in tests
    ```

Inserting a plain sleep
-----------------------
Add ``<!-- test:wait --seconds N -->`` on its own line to emit a ``sleep N``
call at that point in the script:

    <!-- test:wait --seconds 60 -->

Inserting a juju_wait call
--------------------------
Add ``<!-- test:juju-wait -->`` on its own line to emit a ``juju_wait`` call
that polls the Juju model until all units are active/idle.  An optional
``--timeout`` value (seconds) can be supplied:

    <!-- test:juju-wait -->
    <!-- test:juju-wait --timeout 900 -->

Running a block with a timeout (kill after N seconds)
-----------------------------------------------------
Add ``<!-- test:run-with-timeout --seconds N -->`` on the line immediately
before the opening fence to run that block inside ``timeout N`` and ignore the
result.  Useful for commands that run indefinitely until interrupted (e.g.
consumer scripts):

    <!-- test:run-with-timeout --seconds 30 -->
    ```shell
    python3 -m charms.kafka.v0.client ... --consumer
    ```

The block is wrapped in a bash heredoc so multi-line commands work correctly,
and the exit code is discarded (``|| true``) so a ``SIGTERM`` from ``timeout``
does not abort the test script.
"""

import re
import sys
from pathlib import Path

SKIP_MARKER = "<!-- test:skip -->"
_SLEEP_PATTERN = re.compile(r"<!--\s*test:wait\s+--seconds\s+(\d+)\s*-->")
_JUJU_WAIT_PATTERN = re.compile(r"<!--\s*test:juju-wait(?:\s+(--timeout\s+\d+))?\s*-->")
_RUN_WITH_TIMEOUT_PATTERN = re.compile(r"<!--\s*test:run-with-timeout\s+--seconds\s+(\d+)\s*-->")
_SHELL_OPEN = re.compile(r"^```shell\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")


def extract_shell_blocks(source: str) -> list[str]:
    """Return shell code block contents and wait calls from a MyST Markdown string.

    Each returned string is either the raw content between shell fences, a
    ``sleep N`` line from a ``<!-- test:wait -->`` marker, or a
    ``juju_wait [--timeout N]`` line from a ``<!-- test:juju-wait -->`` marker.
    Blocks marked with ``<!-- test:skip -->`` are omitted.
    """
    lines = source.splitlines()
    blocks: list[str] = []
    i = 0
    skip_next = False
    run_with_timeout_seconds: int | None = None

    while i < len(lines):
        line = lines[i]

        # Detect skip marker; remember to skip the next shell block.
        if line.strip() == SKIP_MARKER:
            skip_next = True
            i += 1
            continue

        # Detect plain sleep marker.
        sleep_match = _SLEEP_PATTERN.match(line.strip())
        if sleep_match:
            blocks.append(f"sleep {sleep_match.group(1)}")
            i += 1
            continue

        # Detect juju-wait marker; emit a juju_wait call.
        juju_wait_match = _JUJU_WAIT_PATTERN.match(line.strip())
        if juju_wait_match:
            args = juju_wait_match.group(1)
            blocks.append(f"juju_wait {args}".rstrip() if args else "juju_wait")
            i += 1
            continue

        # Detect run-with-timeout marker; remember the timeout for the next block.
        timeout_match = _RUN_WITH_TIMEOUT_PATTERN.match(line.strip())
        if timeout_match:
            run_with_timeout_seconds = int(timeout_match.group(1))
            i += 1
            continue

        # Opening fence for a shell block.
        if _SHELL_OPEN.match(line):
            i += 1
            block_lines: list[str] = []
            while i < len(lines) and not _FENCE_CLOSE.match(lines[i]):
                block_lines.append(lines[i])
                i += 1
            i += 1  # consume closing fence

            if not skip_next and block_lines:
                content = "\n".join(block_lines)
                if run_with_timeout_seconds is not None:
                    # Wrap in a bash heredoc with timeout so multi-line commands
                    # work and SIGTERM from timeout does not abort the script.
                    blocks.append(
                        f"( timeout {run_with_timeout_seconds} bash << 'TUTORIAL_TIMEOUT_EOF'\n"
                        f"{content}\n"
                        f"TUTORIAL_TIMEOUT_EOF\n) || true"
                    )
                else:
                    blocks.append(content)
            skip_next = False
            run_with_timeout_seconds = None
            continue

        # Non-empty, non-marker line resets the skip flag.
        if line.strip():
            skip_next = False

        i += 1

    return blocks


def build_script(input_path: Path, blocks: list[str]) -> str:
    header = (
        "#!/bin/bash\n"
        f"# Extracted from : {input_path}\n"
        f"# Regenerate with: python3 tests/tutorial/extract_commands.py {input_path} <output.sh>\n"
        "#\n"
        "# To skip a block in the Markdown source, add this comment on the line\n"
        "# immediately before its opening fence (blank lines are fine between them):\n"
        "#   <!-- test:skip -->\n"
        "#\n"
        "# Only ```shell fences are extracted; use any other tag to naturally exclude a block.\n"
        "\n"
        "set -euo pipefail\n"
        "\n"
        "# shellcheck source=tests/tutorial/helpers.sh\n"
        ". \"$SPREAD_PATH/tests/tutorial/helpers.sh\"\n"
        "\n"
    )
    return header + "\n\n".join(blocks) + "\n"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        sys.exit(f"Error: {input_path} does not exist")

    source = input_path.read_text(encoding="utf-8")
    blocks = extract_shell_blocks(source)

    if not blocks:
        print(f"Warning: no shell blocks found in {input_path}", file=sys.stderr)

    script = build_script(input_path, blocks)

    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(script, encoding="utf-8")
        print(f"Written {len(blocks)} block(s) → {output_path}")
    else:
        print(script, end="")


if __name__ == "__main__":
    main()
