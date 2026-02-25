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

## Regenerating an existing script

Re-run the extraction command whenever the tutorial Markdown changes:

```bash
python3 tests/tutorial/extract_commands.py docs/tutorial/environment.md \
    tests/tutorial/01_environment.sh
```

Review the diff before committing – the script is intentionally committed so
changes are visible in PRs.
