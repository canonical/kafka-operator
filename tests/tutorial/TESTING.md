# Tutorial testing with Spread

Automated tests that run the documentation tutorial end-to-end inside a
Multipass VM. Shell commands are extracted from the Markdown tutorial pages
and executed sequentially by the [Spread](https://github.com/canonical/spread)
test framework.

## Overview

The tutorial Markdown files under `docs/tutorial/` are the single source of
truth. Test metadata, wait points, assertions, and hidden commands are all
expressed as HTML comments inside those files — invisible to readers but
consumed by `extract_commands.py`.

The generation pipeline:

1. Each `docs/tutorial/<page>.md` maps to a `tests/tutorial/<NN>_<name>.sh`
   script and a `tests/tutorial/<NN>_<name>/task.yaml` Spread task.
2. `extract_commands.py` extracts `` ```shell `` fenced blocks, processes
   annotations, and writes both the `.sh` script and `task.yaml`.
3. The `Makefile` drives generation for all pages.

Generated files (`.sh` and `task.yaml`) are **not stored in git**. They must
be generated locally before running Spread.

## Prerequisites

- [Multipass](https://documentation.ubuntu.com/multipass/latest/how-to-guides/install-multipass/)
- [Spread](https://github.com/canonical/spread) via Go
  (`go install github.com/snapcore/spread/cmd/spread@latest`), **not** as a snap

## Running the tests

Generate scripts and task files, then run:

```bash
make -f tests/tutorial/Makefile extract
spread -vv -debug multipass:ubuntu-24.04-64:tests/tutorial
```

Run a single stage:

```bash
spread -vv -debug multipass:ubuntu-24.04-64:tests/tutorial/01_environment
```

Use `-continue` to keep going after failures.

Resource defaults (override with env vars):

| Variable          | Default | Purpose                |
|-------------------|---------|------------------------|
| `SPREAD_VM_CPUS`  | `8`     | Multipass VM CPU count |
| `SPREAD_VM_MEM`   | `16G`   | Multipass VM RAM       |
| `SPREAD_VM_DISK`  | `50G`   | Multipass VM disk      |

## Adding a new tutorial page

1. Register the page in the `SCRIPTS` variable in `tests/tutorial/Makefile`.
2. Add a `<!-- test:spread ... -->` block to the Markdown file with `priority`
   and `kill-timeout` (see below).
3. Run `make -f tests/tutorial/Makefile extract` to generate both the `.sh`
   script and `task.yaml`.

## Annotation reference

Annotations are HTML comments in the Markdown source. Only `` ```shell ``
fences are extracted; other tags (`` ```bash ``, `` ```text ``) are ignored.

### `<!-- test:skip -->`

Skip the next `` ```shell `` block.

### `<!-- test:wait --seconds N -->`

Emit `sleep N` at that point in the script.

### `<!-- test:await-idle --timeout S --allow-blocked APP1,APP2 -->`

Emit a `juju wait-for model` command that blocks until all applications are
`active`. `--timeout` is in seconds (default: 600). `--allow-blocked` lists
apps permitted to be in `blocked` state (comma-separated).

### `<!-- test:run-with-timeout --seconds N -->`

Run the next `` ```shell `` block inside `timeout N`; ignore exit code.

### `<!-- test:set-variables ... -->`

Run a command and extract named fields into shell variables. Subsequent
`<field>` placeholders in shell blocks are auto-replaced with `${VAR}`.

```
<!-- test:set-variables
command: juju run data-integrator/leader get-credentials
KAFKA_USERNAME: username
KAFKA_PASSWORD: password
-->
```

### `<!-- test:run ... -->`

Emit hidden shell commands (not visible in rendered docs).

### `<!-- test:assert ... -->`

Like `test:run` but marked as an assertion. Relies on `set -e` to abort on
failure. Use `jq -e`, `grep -q`, or `test` for checks.

```
<!-- test:assert
juju status --format json | jq -e '.applications.kafka.units | length == 3'
-->
```

### `<!-- test:spread ... -->`

Spread task metadata. Used to generate `task.yaml`. Not emitted into scripts.

```
<!-- test:spread
priority: 200
kill-timeout: 30m
-->
```
