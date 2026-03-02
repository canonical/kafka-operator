# Tutorial testing with Spread

This directory contains automated tests that run the documentation tutorial
end-to-end inside a Multipass VM.

## Prerequisites

- [Multipass](https://documentation.ubuntu.com/multipass/latest/how-to-guides/install-multipass/) installed locally
- [Spread](https://github.com/canonical/spread) installed via Go (`go install github.com/canonical/spread/cmd/spread@latest`), **not** as a snap

## Directory layout

```
spread.yaml                       # Spread project config (project root)
tests/tutorial/
  helpers.sh                        # Shared helpers – source in every task
  extract_commands.py               # Extracts shell blocks from Markdown
  task.yaml                         # Spread task (all tutorial pages in order)
  01_environment.sh                 # Generated from docs/tutorial/environment.md
  02_deploy.sh                      # (future) docs/tutorial/deploy.md
  …
```

## Running the tests

List available tests (dry-run):
```bash
spread --list
```

Run the tutorial test suite:
```bash
spread -vv -debug multipass:ubuntu-24.04-64:tests/tutorial
```

The VM is provisioned automatically and deleted on completion.  
On failure `--debug` drops you into a shell inside the VM.

Resource defaults (override with env vars):

| Variable          | Default | Purpose                |
|-------------------|---------|------------------------|
| `SPREAD_VM_CPUS`  | `8`     | Multipass VM CPU count |
| `SPREAD_VM_MEM`   | `16G`   | Multipass VM RAM       |
| `SPREAD_VM_DISK`  | `50G`   | Multipass VM disk      |

## Adding tests for a new tutorial page

1. **Mark any blocks to skip** in the Markdown source by adding
   `<!-- test:skip -->` on the line immediately before the `shell` fence:

   ````markdown
   <!-- test:skip -->
   ```shell
   watch juju status --color   ← runs forever; skip in tests
   ```
   ````

   Any fence that is **not** ` ```shell ` (e.g. ` ```bash `, ` ```text `) is
   automatically excluded.

2. **Generate the script** from the Markdown source:

   ```bash
   python3 tests/tutorial/extract_commands.py docs/tutorial/<page>.md \
       tests/tutorial/<NN>_<page>.sh
   ```

3. **Uncomment the corresponding line** in `tests/tutorial/task.yaml`.

4. **Add `juju_wait` calls** where the tutorial says _"wait until
   active/idle"_.  The helper is sourced automatically from `helpers.sh`:

   ```bash
   juju_wait --timeout 900   # 15 min; default is 10 min
   ```

5. **Run a block with a timeout** for commands that run indefinitely until
   interrupted (e.g. consumer scripts).  Add
   `<!-- test:run-with-timeout --seconds N -->` on the line immediately before
   the opening fence:

   ````markdown
   <!-- test:run-with-timeout --seconds 30 -->
   ```shell
   python3 -m charms.kafka.v0.client ... --consumer
   ```
   ````

   The block is wrapped with `timeout N bash << '...'` and the exit code is
   discarded, so a `SIGTERM` from `timeout` does not abort the test script.

6. **Run a command and store fields into shell variables** for shell blocks that
   use placeholder values like `<username>` or `<endpoints>`.  Add a
   `<!-- test:set-variables ... -->` block at the point where the values become
   available:

   ````markdown
   <!-- test:set-variables
   command: juju run data-integrator/leader get-credentials
   KAFKA_USERNAME: username
   KAFKA_PASSWORD: password
   KAFKA_ENDPOINTS: endpoints
   -->
   ````

   The `command:` line is the shell command to run.  Every other `VARNAME: field`
   line greps the output for `field:` and stores the value in `$VARNAME`.  From
   that point onward, all extracted `shell` blocks have their matching literal
   placeholders (e.g. `<username>`) automatically replaced with the corresponding
   shell-variable references (e.g. `${KAFKA_USERNAME}`), so the Markdown source
   stays human-readable while the test script uses real values.

## Regenerating an existing script

Re-run the extraction command whenever the tutorial Markdown changes:

```bash
python3 tests/tutorial/extract_commands.py docs/tutorial/environment.md \
    tests/tutorial/01_environment.sh
```

Review the diff before committing – the script is intentionally committed so
changes are visible in PRs.
