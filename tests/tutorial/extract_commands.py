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
"""

import re
import sys
from pathlib import Path

SKIP_MARKER = "<!-- test:skip -->"
_SHELL_OPEN = re.compile(r"^```shell\s*$")
_FENCE_CLOSE = re.compile(r"^```\s*$")


def extract_shell_blocks(source: str) -> list[str]:
    """Return shell code block contents from a MyST Markdown string.

    Each returned string is the raw content between the fences, with the
    fences themselves stripped.  Blocks marked with SKIP_MARKER are omitted.
    """
    lines = source.splitlines()
    blocks: list[str] = []
    i = 0
    skip_next = False

    while i < len(lines):
        line = lines[i]

        # Detect skip marker; remember to skip the next shell block.
        if line.strip() == SKIP_MARKER:
            skip_next = True
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
                blocks.append("\n".join(block_lines))
            skip_next = False
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
