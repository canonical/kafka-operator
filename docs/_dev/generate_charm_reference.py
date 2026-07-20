#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Generate reference Markdown pages from charm source files.

This script parses ``actions.yaml`` and ``config.yaml`` from the machine charm
and emits MyST Markdown into ``docs/reference/_generated/`` (which is
gitignored). It runs as a pre-build step in ``docs/Makefile`` before
Sphinx reads any Markdown files, so the published docs always reflect the
current state of the charm metadata.

The output mirrors the content Charmhub auto-generates for the
``/kafka/actions`` and ``/kafka/configure`` pages, but is produced locally
from the same source files Charmhub itself uses (``actions.yaml`` and
``config.yaml`` bundled into the ``.charm`` artifact at pack time).

Usage:
    python3 _dev/generate_charm_reference.py

Outputs:
    docs/reference/_generated/actions.md
    docs/reference/_generated/configurations.md
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

# Resolve paths relative to this script so it works regardless of CWD.
# Script:  docs/_dev/generate_charm_reference.py
# Repo:    <repo root>
# Docs:    docs/
# Machine: machine/
SCRIPT_PATH = Path(__file__).resolve()
DEV_DIR = SCRIPT_PATH.parent                  # docs/_dev
DOCS_DIR = DEV_DIR.parent                     # docs
REPO_ROOT = DOCS_DIR.parent                   # <repo root>
MACHINE_DIR = REPO_ROOT / "machine"
OUTPUT_DIR = DOCS_DIR / "reference" / "_generated"

ACTIONS_FILE = MACHINE_DIR / "actions.yaml"
CONFIG_FILE = MACHINE_DIR / "config.yaml"


def _load_yaml(path: Path) -> Any:
    """Load a YAML file and return its parsed content."""
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _format_default(value: Any) -> str:
    """Format a default value for display in a Markdown table cell."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Quote empty strings so the table cell is visible; leave others bare.
        return f'`"{value}"`' if value == "" else f"`{value}`"
    return f"`{value}`"


def _format_description(desc: Any) -> str:
    """Normalise a description field into a single-line Markdown string.

    YAML block scalars and multi-line plain scalars arrive with embedded
    newlines and extra indentation. Collapse whitespace so the table cell
    renders cleanly.
    """
    if desc is None:
        return ""
    text = str(desc).strip()
    # Collapse runs of whitespace (including newlines) to single spaces.
    return " ".join(text.split())


def _format_param_description(desc: Any) -> str:
    """Format a parameter description, preserving code blocks where possible.

    Parameter descriptions often contain inline code and multi-line examples.
    We collapse whitespace but keep backtick-delimited spans intact.
    """
    return _format_description(desc)


def generate_actions_page(actions_data: dict[str, Any]) -> str:
    """Render the Actions reference page as MyST Markdown.

    Mirrors the layout of https://charmhub.io/kafka/actions: one section per
    action, with the description followed by a parameters table.
    """
    lines: list[str] = []
    lines.append("---")
    lines.append("myst:")
    lines.append("  html_meta:")
    lines.append('    description: "Charmed Apache Kafka actions reference - '
                 'complete list of juju actions with parameters, types, and defaults."')
    lines.append("---")
    lines.append("")
    lines.append("(reference-actions)=")
    lines.append("# Actions")
    lines.append("")
    lines.append(
        "The following actions can be run on the Charmed Apache Kafka charm "
        "using `juju run`. This page is generated from "
        "[`machine/actions.yaml`](https://github.com/canonical/kafka-operator/blob/main/machine/actions.yaml) "
        "at build time."
    )
    lines.append("")
    lines.append("```{note}")
    lines.append("This page is auto-generated. Do not edit it directly; edit "
                 "`machine/actions.yaml` instead.")
    lines.append("```")
    lines.append("")

    for action_name, spec in actions_data.items():
        if not isinstance(spec, dict):
            continue
        lines.append(f"## `{action_name}`")
        lines.append("")
        description = spec.get("description")
        if description:
            # Render multi-line descriptions as a blockquote for readability.
            for desc_line in str(description).strip().split("\n"):
                lines.append(f"> {desc_line.strip()}" if desc_line.strip() else ">")
            lines.append("")

        params = spec.get("params") or {}
        required = spec.get("required") or []
        additional_properties = spec.get("additionalProperties")

        if params:
            lines.append("### Parameters")
            lines.append("")
            lines.append("| Name | Type | Default | Required | Description |")
            lines.append("|---|---|---|---|---|")
            for param_name, param_spec in params.items():
                p_type = param_spec.get("type", "") if isinstance(param_spec, dict) else ""
                p_default = param_spec.get("default") if isinstance(param_spec, dict) else None
                p_desc = param_spec.get("description", "") if isinstance(param_spec, dict) else ""
                is_required = "yes" if param_name in required else ""
                lines.append(
                    f"| `{param_name}` | `{p_type}` | "
                    f"{_format_default(p_default)} | {is_required} | "
                    f"{_format_param_description(p_desc)} |"
                )
            lines.append("")

            # Emit constraints (enum / minimum) that don't fit the table.
            for param_name, param_spec in params.items():
                if not isinstance(param_spec, dict):
                    continue
                enum = param_spec.get("enum")
                minimum = param_spec.get("minimum")
                if enum or minimum is not None:
                    lines.append(f"- `{param_name}` constraints:")
                    if enum:
                        lines.append(f"  - Allowed values: "
                                     f"{', '.join(f'`{v}`' for v in enum)}")
                    if minimum is not None:
                        lines.append(f"  - Minimum: `{minimum}`")
            if any(
                isinstance(p, dict) and (p.get("enum") or p.get("minimum") is not None)
                for p in params.values()
            ):
                lines.append("")

        if additional_properties is False:
            lines.append("No additional parameters are accepted.")
            lines.append("")

    return "\n".join(lines) + "\n"


def generate_configurations_page(config_data: dict[str, Any]) -> str:
    """Render the Configurations reference page as MyST Markdown.

    Mirrors the layout of https://charmhub.io/kafka/configure: a single table
    listing every configuration option with its type, default, and description.
    """
    lines: list[str] = []
    lines.append("---")
    lines.append("myst:")
    lines.append("  html_meta:")
    lines.append('    description: "Charmed Apache Kafka configuration options '
                 'reference - types, defaults, and descriptions for all config options."')
    lines.append("---")
    lines.append("")
    lines.append("(reference-configurations)=")
    lines.append("# Configurations")
    lines.append("")
    lines.append(
        "The following configuration options can be set on the Charmed Apache "
        "Kafka charm using `juju config`. This page is generated from "
        "[`machine/config.yaml`](https://github.com/canonical/kafka-operator/blob/main/machine/config.yaml) "
        "at build time."
    )
    lines.append("")
    lines.append("```{note}")
    lines.append("This page is auto-generated. Do not edit it directly; edit "
                 "`machine/config.yaml` instead.")
    lines.append("```")
    lines.append("")

    options = config_data.get("options") or {}
    if not options:
        lines.append("No configuration options defined.")
        lines.append("")
        return "\n".join(lines) + "\n"

    lines.append("| Name | Type | Default | Description |")
    lines.append("|---|---|---|---|")
    for opt_name, opt_spec in options.items():
        if not isinstance(opt_spec, dict):
            continue
        o_type = opt_spec.get("type", "")
        o_default = opt_spec.get("default")
        o_desc = opt_spec.get("description", "")
        lines.append(
            f"| `{opt_name}` | `{o_type}` | {_format_default(o_default)} | "
            f"{_format_description(o_desc)} |"
        )
    lines.append("")
    lines.append(
        "See the [Juju documentation](https://canonical.com/juju/docs/juju/cli/commands/"
        "juju-config) for more information on configuring applications."
    )
    lines.append("")

    return "\n".join(lines) + "\n"


def main() -> int:
    """Generate the reference pages and write them to the output directory."""
    if not ACTIONS_FILE.exists():
        print(f"ERROR: actions file not found: {ACTIONS_FILE}", file=sys.stderr)
        return 1
    if not CONFIG_FILE.exists():
        print(f"ERROR: config file not found: {CONFIG_FILE}", file=sys.stderr)
        return 1

    actions_data = _load_yaml(ACTIONS_FILE)
    config_data = _load_yaml(CONFIG_FILE)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    actions_md = generate_actions_page(actions_data)
    config_md = generate_configurations_page(config_data)

    actions_out = OUTPUT_DIR / "actions.md"
    config_out = OUTPUT_DIR / "configurations.md"

    actions_out.write_text(actions_md, encoding="utf-8")
    config_out.write_text(config_md, encoding="utf-8")

    print(f"Generated {actions_out.relative_to(REPO_ROOT)} "
          f"({len(actions_data)} actions)")
    print(f"Generated {config_out.relative_to(REPO_ROOT)} "
          f"({len(config_data.get('options') or {})} config options)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
