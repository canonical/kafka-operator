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

Annotations
-----------
Annotations are HTML comments placed before or between fenced code blocks.
They control how blocks are extracted and what additional commands are emitted.
See TESTING.md for full reference.
"""

import re
import shlex
import sys
from pathlib import Path

SKIP_MARKER = "<!-- test:skip -->"
_SLEEP_PATTERN = re.compile(r"<!--\s*test:wait\s+--seconds\s+(\d+)\s*-->")
_AWAIT_IDLE_PATTERN = re.compile(r"<!--\s*test:await-idle(.*?)-->")
_RUN_WITH_TIMEOUT_PATTERN = re.compile(r"<!--\s*test:run-with-timeout\s+--seconds\s+(\d+)\s*-->")
_SET_VARIABLES_START = re.compile(r"<!--\s*test:set-variables\s*$")
_RUN_HIDDEN_START = re.compile(r"<!--\s*test:run\s*$")
_ASSERT_START = re.compile(r"<!--\s*test:assert\s*$")
_SPREAD_META_START = re.compile(r"<!--\s*test:spread\s*$")
_SHELL_OPEN = re.compile(r"^```shell\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")


def _seconds_to_go_duration(seconds: int) -> str:
    """Convert seconds to Go duration format (e.g. 600 -> '10m', 90 -> '1m30s')."""
    if seconds <= 0:
        return "10m"
    m, s = divmod(seconds, 60)
    if s == 0:
        return f"{m}m"
    return f"{m}m{s}s"


def _build_await_idle_command(args_str: str) -> str:
    """Build a ``juju wait-for model`` command from await-idle annotation args."""
    timeout = 1200
    allow_blocked: list[str] = []

    tokens = shlex.split(args_str) if args_str.strip() else []
    i = 0
    while i < len(tokens):
        if tokens[i] == "--timeout" and i + 1 < len(tokens):
            timeout = int(tokens[i + 1])
            i += 2
        elif tokens[i] == "--allow-blocked" and i + 1 < len(tokens):
            allow_blocked = [a.strip() for a in tokens[i + 1].split(",") if a.strip()]
            i += 2
        else:
            i += 1

    duration = _seconds_to_go_duration(timeout)

    if allow_blocked:
        app_conditions = " || ".join(f'app.name == "{name}"' for name in allow_blocked)
        query = f'forEach(applications, app => app.status == "active" || {app_conditions})'
    else:
        query = 'forEach(applications, app => app.status == "active")'

    # Small sleep before we start polling. Without this, the
    # wait-for can see the pre-command "active" state and exit immediately.
    return (
        "sleep 3\n"
        f"juju wait-for model tutorial --query='{query}' --timeout {duration}"
    )


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


def _parse_run_hidden_block(
    lines: list[str], start: int, active_substitutions: list[tuple[str, str]]
) -> tuple[str, int]:
    """Parse a <!-- test:run ... --> block starting at line `start`.

    Returns (bash_snippet, next_index).
    """
    i = start + 1
    cmd_lines: list[str] = []

    while i < len(lines):
        raw = lines[i]
        if "-->" in raw:
            i += 1
            break
        stripped = raw.rstrip()
        if stripped:
            cmd_lines.append(stripped)
        i += 1

    content = "\n".join(cmd_lines)
    for placeholder, variable in active_substitutions:
        content = content.replace(placeholder, variable)
    return content, i


def _handle_marker_line(
    line: str,
    blocks: list[str],
) -> str | None:
    """Check *line* for a standalone annotation marker.

    Returns a short tag (``"skip"``, ``"sleep"``, ``"await_idle"``) when
    the line was consumed, or ``None`` when the line is not a marker.
    """
    stripped = line.strip()

    if stripped == SKIP_MARKER:
        return "skip"

    sleep_match = _SLEEP_PATTERN.match(stripped)
    if sleep_match:
        blocks.append(f"sleep {sleep_match.group(1)}")
        return "sleep"

    await_idle_match = _AWAIT_IDLE_PATTERN.match(stripped)
    if await_idle_match:
        args = await_idle_match.group(1).strip()
        blocks.append(_build_await_idle_command(args))
        return "await_idle"

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
    """Return shell code block contents and generated commands from a MyST Markdown string.

    Each returned string is either the raw content between shell fences, a
    ``sleep N`` line, a ``juju wait-for model`` command, or injected code from
    other annotations.  Blocks marked with ``<!-- test:skip -->`` are omitted.
    """
    lines = source.splitlines()
    blocks: list[str] = []
    i = 0
    skip_next = False
    run_with_timeout_seconds: int | None = None
    active_substitutions: list[tuple[str, str]] = []

    while i < len(lines):
        line = lines[i]

        # Detect standalone annotation markers (skip / sleep / await_idle).
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

        # Detect spread meta block; skip silently (used for task.yaml generation).
        if _SPREAD_META_START.match(line.strip()):
            while i < len(lines) and "-->" not in lines[i]:
                i += 1
            i += 1  # skip closing -->
            continue

        # Detect assert block; emit commands with assertion comment.
        if _ASSERT_START.match(line.strip()):
            snippet, i = _parse_run_hidden_block(lines, i, active_substitutions)
            if snippet:
                blocks.append(f"# --- Test assertion ---\n{snippet}")
            continue

        # Detect run-hidden block; emit commands invisible to the reader.
        if _RUN_HIDDEN_START.match(line.strip()):
            snippet, i = _parse_run_hidden_block(lines, i, active_substitutions)
            if snippet:
                blocks.append(snippet)
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
        "# Only ```shell fences are extracted; use any other tag to naturally exclude a block.\n"
        "\n"
        "set -euo pipefail\n"
        "\n"
        "# Spread SSHs in as root but does not always set HOME=/root.\n"
        "export HOME=/root\n"
        "\n"
    )
    return header + "\n\n".join(blocks) + "\n"


def extract_spread_meta(source: str) -> dict[str, str]:
    """Extract spread test metadata from a ``<!-- test:spread ... -->`` block."""
    lines = source.splitlines()
    for i, line in enumerate(lines):
        if _SPREAD_META_START.match(line.strip()):
            meta: dict[str, str] = {}
            j = i + 1
            while j < len(lines):
                raw = lines[j]
                if "-->" in raw:
                    break
                stripped = raw.strip()
                if stripped and ":" in stripped:
                    key, _, value = stripped.partition(":")
                    meta[key.strip()] = value.strip()
                j += 1
            return meta
    return {}


def extract_heading(source: str) -> str:
    """Return the text of the first Markdown heading."""
    for line in source.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def build_task_yaml(script_path: str, heading: str, meta: dict[str, str]) -> str:
    """Generate a Spread task.yaml file."""
    priority = meta.get("priority", "0")
    kill_timeout = meta.get("kill-timeout", "30m")
    summary = heading or script_path
    return (
        f'summary: "{summary}"\n'
        f"priority: {priority}\n"
        f"kill-timeout: {kill_timeout}\n"
        f"execute: |\n"
        f'  bash "$SPREAD_PATH/{script_path}"\n'
    )


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

        # Generate task.yaml alongside the .sh file if spread metadata exists.
        meta = extract_spread_meta(source)
        heading = extract_heading(source)
        if meta:
            task_dir = output_path.with_suffix("")  # 01_environment.sh → 01_environment/
            task_yaml = task_dir / "task.yaml"
            task_yaml.parent.mkdir(parents=True, exist_ok=True)
            task_content = build_task_yaml(str(output_path), heading, meta)
            task_yaml.write_text(task_content, encoding="utf-8")
            print(f"Written task.yaml → {task_yaml}")
    else:
        print(script, end="")


if __name__ == "__main__":
    main()
