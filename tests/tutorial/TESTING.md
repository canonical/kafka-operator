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

- Ubuntu host machine (tested on 24.04)
- [Multipass](https://documentation.ubuntu.com/multipass/latest/how-to-guides/install-multipass/)
- [Go](https://go.dev/doc/install)
- [Spread](https://github.com/canonical/spread) installed via Go (**not** as a snap):
  ```bash
  go install github.com/snapcore/spread/cmd/spread@latest
  ```
- Python 3 and `make` (usually pre-installed on Ubuntu)

## Quick start

From a fresh clone:

```bash
git clone <repo-url> && cd kafka-operator

# 1. Generate the .sh scripts and task.yaml files from Markdown sources.
tox -e tutorial-extract

# 2. Run the full tutorial test suite (extract + spread).
#    Aborts on the first failure, tears down the VM on completion.
tox -e tutorial
```

Alternatively, you can use the Makefile directly:

```bash
make -f tests/tutorial/Makefile extract   # step 1
make -f tests/tutorial/Makefile test      # steps 1+2
```

The `tutorial` tox env (and the Makefile `test` target) uses `-abend` so that
the run stops immediately when a step fails. Since every tutorial stage depends
on the previous one, continuing after a failure would only produce cascading
errors.

### Run modes

| tox / Make                                 | Spread flags        | Behaviour                                                     |
|--------------------------------------------|---------------------|---------------------------------------------------------------|
| `tox -e tutorial` / `make … test`          | `-abend -vv`        | Abort on first failure, tear down VM                          |
| `tox -e tutorial-extract` / `make … extract` | —                 | Generate scripts only (no Spread run)                         |
| `make … test-continue`                     | `-vv`               | Run all stages even if earlier ones fail                      |
| `make … test-debug`                        | `-abend -vv -debug` | Abort on first failure, drop into an interactive VM shell     |

**`test-debug`** is the most useful mode during development. When a step fails,
Spread pauses and prints SSH credentials for the VM. You can SSH in, inspect
`juju status`, read logs, re-run commands by hand, then type `exit` (or
`Ctrl+D`) to let Spread clean up. Example:

```bash
make -f tests/tutorial/Makefile test-debug
```

On failure you'll see output like:

```
2026-04-11 20:13:23 Debug shell on multipass:ubuntu-24.04-64 for multipass:ubuntu-24.04-64:tests/tutorial/03_client
2026-04-11 20:13:23   Address: 10.189.154.39:22
2026-04-11 20:13:23   User:    root
2026-04-11 20:13:23   Password: 6d11d3739e023950
```

Use those credentials to SSH in:

```bash
ssh root@10.189.154.39     # password from the output above
cd /charmed-kafka
juju status                 # inspect the model
bash tests/tutorial/03_client.sh   # re-run the failing script
```

When done, exit the shell and Spread will tear down the VM.

### Running directly with `spread`

You can also call `spread` directly for finer control:

```bash
# Abort on first failure (recommended for sequential tutorial):
spread -abend -vv multipass:ubuntu-24.04-64:tests/tutorial/

# Run all stages regardless of failures:
spread -vv multipass:ubuntu-24.04-64:tests/tutorial/

# Debug mode — interactive shell on failure:
spread -abend -vv -debug multipass:ubuntu-24.04-64:tests/tutorial/

# Run a single stage:
spread -abend -vv -debug multipass:ubuntu-24.04-64:tests/tutorial/02_deploy
```

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

Emit a `wait_idle` call (from `helpers.sh`) that polls `juju status` until all
units are `active/idle`. `--timeout` is in seconds (default: 1200).
`--allow-blocked` lists apps permitted to be in `blocked` state
(comma-separated).

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
