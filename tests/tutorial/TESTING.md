# Tutorial testing with Spread

This directory contains automated tests that run the documentation tutorial
end-to-end inside a Multipass VM.

## Prerequisites

- [Multipass](https://documentation.ubuntu.com/multipass/latest/how-to-guides/install-multipass/) installed locally
- [Spread](https://github.com/canonical/spread) installed via Go (`go install github.com/snapcore/spread/cmd/spread@latest`), **not** as a snap

## Directory layout

```text
spread.yaml                       # Spread project config (project root)
tests/tutorial/
  Makefile                          # Generates .sh scripts from Markdown sources
  helpers.sh                        # Shared helpers – sourced in every task
  extract_commands.py               # Extracts shell blocks from Markdown
  01_environment/task.yaml          # Spread task for environment.md
  01_environment.sh                 # Generated from docs/tutorial/environment.md
  02_deploy/task.yaml               # Spread task for deploy.md
  02_deploy.sh                      # Generated from docs/tutorial/deploy.md
  …
```

## Running the tests

List available tests (dry-run):

```bash
spread --list
```

Run the full tutorial test suite:

```bash
spread -vv -debug multipass:ubuntu-24.04-64:tests/tutorial
```

Run a single stage:

```bash
spread -vv -debug multipass:ubuntu-24.04-64:tests/tutorial/01_environment
```

By default Spread stops on the first failure. Use `-continue` to run all
remaining tasks regardless:

```bash
spread -continue -vv -debug multipass:ubuntu-24.04-64:tests/tutorial
```

The VM is provisioned automatically and deleted on completion.
On failure, `-debug` drops you into a shell inside the VM for inspection.

Resource defaults (override with env vars):

| Variable          | Default | Purpose                |
|-------------------|---------|------------------------|
| `SPREAD_VM_CPUS`  | `8`     | Multipass VM CPU count |
| `SPREAD_VM_MEM`   | `16G`   | Multipass VM RAM       |
| `SPREAD_VM_DISK`  | `50G`   | Multipass VM disk      |

## Writing tutorial test scripts

Each tutorial page maps to a generated `.sh` script and a Spread task
directory.  The scripts are committed so that changes are visible in PRs.

### Generating scripts

Scripts are produced by `extract_commands.py`, which pulls every ` ```shell `
fence out of a Markdown file.  The Makefile drives this for all pages.

Regenerate only out-of-date scripts (checks timestamps):

```bash
make -f tests/tutorial/Makefile        # from the project root
# or, from tests/tutorial/:
make
```

Force-regenerate all scripts unconditionally:

```bash
make -f tests/tutorial/Makefile extract
```

To generate a single script directly:

```bash
python3 tests/tutorial/extract_commands.py docs/tutorial/<page>.md \
    tests/tutorial/<NN>_<page>.sh
```

To **add a new tutorial page**, register it in the `SCRIPTS` variable at the
top of `tests/tutorial/Makefile`, then run `make`.  Create a matching task
directory (e.g. `tests/tutorial/04_newpage/task.yaml`) that executes the
generated script:

```yaml
summary: "Tutorial stage 4 – <page title>"
execute: |
  bash "$SPREAD_PATH/tests/tutorial/04_newpage.sh"
```

### Test annotations

Annotations are HTML comments placed immediately before a fenced code block in
the Markdown source.  They control how `extract_commands.py` handles the block.

> Only ` ```shell ` fences are extracted by default.  Fences tagged
> ` ```bash `, ` ```text `, etc. are always skipped.

#### Skip a block

````markdown
<!-- test:skip -->
```shell
watch juju status --color   # runs forever – skip in tests
```
````

#### Run a block with a timeout

Wraps the block with `timeout N bash`; a `SIGTERM` from the timeout does **not**
abort the test script.

````markdown
<!-- test:run-with-timeout --seconds 30 -->
```shell
python3 -m charms.kafka.v0.client ... --consumer
```
````

#### Extract command output into variables

Use this for blocks that contain placeholder values like `<username>` or
`<endpoints>`.  Place the annotation at the point where the values first become
available:

```markdown
<!-- test:set-variables
command: juju run data-integrator/leader get-credentials
KAFKA_USERNAME: username
KAFKA_PASSWORD: password
KAFKA_ENDPOINTS: endpoints
-->
```

The `command:` line is the shell command to run.  Each `VARNAME: field` line
greps the output for `field:` and stores the result in `$VARNAME`.  From that
point onward all extracted `shell` blocks have their matching placeholders
(e.g. `<username>`) replaced with shell-variable references
(e.g. `${KAFKA_USERNAME}`), keeping the Markdown source human-readable.

### Waiting for Juju

Use `juju_wait` wherever the tutorial instructs the reader to wait until units
are active/idle.  The helper is sourced automatically from `helpers.sh`.

```bash
juju_wait                  # default timeout: 600 s (10 min)
juju_wait --timeout 900    # override to 15 min
juju_wait --interval 60    # poll every 60 s instead of 30 s
```

`juju_wait` polls `juju status` and prints progress at each interval.  It
returns 0 when all units are active/idle, or 1 if the timeout is reached.
