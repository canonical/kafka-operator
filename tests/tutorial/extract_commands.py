#!/usr/bin/env python3
"""Extract shell code blocks from MyST Markdown tutorial files.

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

Running a command and storing fields into shell variables
---------------------------------------------------------
Add a ``<!-- test:set-variables ... -->`` block on its own lines to run an
arbitrary command and parse named fields from its output into shell variables::

    <!-- test:set-variables
    command: juju run data-integrator/leader get-credentials
    KAFKA_USERNAME: username
    KAFKA_PASSWORD: password
    KAFKA_ENDPOINTS: endpoints
    -->

The ``command:`` line specifies the shell command to run.  Every other
``VARNAME: field`` line instructs the extractor to grep the command output for
``field:`` and store the value (second whitespace-delimited token on that line)
into ``$VARNAME``.

From that point onward, any extracted shell block that contains a literal
placeholder matching one of the declared field names (e.g. ``<username>``,
``<endpoints>``) will have it automatically replaced with the corresponding
shell-variable reference (e.g. ``${KAFKA_USERNAME}``), so the Markdown source
keeps its human-readable placeholders while the generated test script uses real
values.
"""

import re
import sys
from pathlib import Path

SKIP_MARKER = "<!-- test:skip -->"
_SLEEP_PATTERN = re.compile(r"<!--\s*test:wait\s+--seconds\s+(\d+)\s*-->")
_JUJU_WAIT_PATTERN = re.compile(r"<!--\s*test:juju-wait(?:\s+(--timeout\s+\d+))?\s*-->")
_RUN_WITH_TIMEOUT_PATTERN = re.compile(r"<!--\s*test:run-with-timeout\s+--seconds\s+(\d+)\s*-->")
_SET_VARIABLES_START = re.compile(r"<!--\s*test:set-variables\s*$")
_SHELL_OPEN = re.compile(r"^```shell\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")


def _parse_set_variables_block(
    lines: list[str], start: int
) -> tuple[str, list[tuple[str, str]], int]:
    """Parse a <!-- test:set-variables ... --> block starting at line `start`.

    Returns (bash_snippet, substitutions, next_index) where:
      - bash_snippet     is the generated variable-assignment bash code
      - substitutions    is [(placeholder, shell_var_ref), ...] for later replacement
      - next_index       is the index of the first line after the closing -->
    """
    i = start + 1
    command = ""
    mappings: list[tuple[str, str]] = []  # [(var_name, field_name), ...]

    while i < len(lines):
        raw = lines[i]
        if "-->" in raw:
            i += 1
            break
        stripped = raw.strip()
        if stripped and ":" in stripped:
            key, _, value = stripped.partition(":")
            key, value = key.strip(), value.strip()
            if key == "command":
                command = value
            elif key and value:
                mappings.append((key, value))
        i += 1

    if not command:
        return "", [], i

    snippet_lines = [f"_CMD_OUTPUT=$({command})"]
    substitutions: list[tuple[str, str]] = []
    for var_name, field_name in mappings:
        snippet_lines.append(
            f"{var_name}=$(echo \"$_CMD_OUTPUT\" | grep '{field_name}:' | awk '{{print $2}}')"
        )
        substitutions.append((f"<{field_name}>", f"${{{var_name}}}"))

    return "\n".join(snippet_lines), substitutions, i


def _handle_marker_line(
    line: str,
    blocks: list[str],
) -> str | None:
    """Check *line* for a standalone annotation marker.

    Returns a short tag (``"skip"``, ``"sleep"``, ``"juju_wait"``) when
    the line was consumed, or ``None`` when the line is not a marker.
    """
    stripped = line.strip()

    if stripped == SKIP_MARKER:
        return "skip"

    sleep_match = _SLEEP_PATTERN.match(stripped)
    if sleep_match:
        blocks.append(f"sleep {sleep_match.group(1)}")
        return "sleep"

    juju_wait_match = _JUJU_WAIT_PATTERN.match(stripped)
    if juju_wait_match:
        args = juju_wait_match.group(1)
        blocks.append(f"juju_wait {args}".rstrip() if args else "juju_wait")
        return "juju_wait"

    return None


def _collect_shell_block(
    lines: list[str],
    start: int,
    skip: bool,
    timeout_seconds: int | None,
    active_substitutions: list[tuple[str, str]],
    blocks: list[str],
) -> int:
    """Read a shell fence starting at *start* (one past the opening fence).

    Appends the processed content to *blocks* (unless *skip* is True) and
    returns the index of the first line after the closing fence.
    """
    i = start
    block_lines: list[str] = []
    while i < len(lines) and not _FENCE_CLOSE.match(lines[i]):
        block_lines.append(lines[i])
        i += 1
    i += 1  # consume closing fence

    if not skip and block_lines:
        content = "\n".join(block_lines)
        for placeholder, variable in active_substitutions:
            content = content.replace(placeholder, variable)
        if timeout_seconds is not None:
            blocks.append(
                f"( timeout {timeout_seconds} bash << 'TUTORIAL_TIMEOUT_EOF'\n"
                f"{content}\n"
                f"TUTORIAL_TIMEOUT_EOF\n) || true"
            )
        else:
            blocks.append(content)
    return i


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
    active_substitutions: list[tuple[str, str]] = []

    while i < len(lines):
        line = lines[i]

        # Detect standalone annotation markers (skip / sleep / juju_wait).
        marker = _handle_marker_line(line, blocks)
        if marker == "skip":
            skip_next = True
            i += 1
            continue
        if marker is not None:
            i += 1
            continue

        # Detect run-with-timeout marker; remember the timeout for the next block.
        timeout_match = _RUN_WITH_TIMEOUT_PATTERN.match(line.strip())
        if timeout_match:
            run_with_timeout_seconds = int(timeout_match.group(1))
            i += 1
            continue

        # Detect set-variables block; emit a variable-extraction snippet.
        if _SET_VARIABLES_START.match(line.strip()):
            snippet, substitutions, i = _parse_set_variables_block(lines, i)
            if snippet:
                blocks.append(snippet)
                active_substitutions.extend(substitutions)
            continue

        # Opening fence for a shell block.
        if _SHELL_OPEN.match(line):
            i = _collect_shell_block(
                lines, i + 1, skip_next, run_with_timeout_seconds,
                active_substitutions, blocks,
            )
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
