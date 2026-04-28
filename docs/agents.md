# Documentation agents guide

## Build

From the `docs/` directory:

```bash
make clean   # remove build artifacts and virtual environment
make run     # install dependencies, build, and serve with live reload at http://127.0.0.1:8000
```

## Stack

- **Sphinx** built and hosted on **Read the Docs**
- **MyST** Markdown (`.md`) is the default syntax — use MyST directives, not reStructuredText
- **Canonical Sphinx extension** provides branding and custom roles; see `conf.py` for configuration

## Documentation guidelines

All documentation follows the [Diátaxis](https://diataxis.fr) framework.
Place content in the correct directory:

| Directory | Purpose | Audience goal |
|-----------|---------|---------------|
| `tutorial/` | Learning-oriented, step-by-step | Acquire skills |
| `how-to/` | Task-oriented, goal-focused | Solve a specific problem |
| `reference/` | Information-oriented, factual | Look something up |
| `explanation/` | Understanding-oriented | Understand why |

**Rules:**
- Do not mix types — a how-to must not explain concepts; an explanation must not give instructions
- Use second person ("you") in tutorials and how-tos
- Reference pages must be accurate and complete; avoid prose padding
- Use reuse snippets in `reuse/` for repeated content

## File conventions

- Filenames: lowercase, hyphen-separated (e.g., `manage-units.md`)
- Every page needs a unique reference label at the top: `(label-name)=`
- MyST front matter (`---`) is used for SEO metadata (`html_meta.description`)
- All documentation pages should be added to a toc-tree of a parent page to be included in the Nav Menu

## Tutorial testing annotations

Pages under `docs/tutorial/` are the single source of truth for both rendered
documentation and automated end-to-end tests (see `tests/tutorial/TESTING.md`).

Commands are extracted **only** from `` ```shell `` fenced blocks.
Use `` ```bash `` or `` ```text `` for output examples or commands that should
not be executed by the test harness.

Test metadata is embedded as HTML comments, invisible to readers:

- `<!-- test:skip -->` — skip the next shell block
- `<!-- test:wait --seconds N -->` — emit `sleep N`
- `<!-- test:await-idle -->` — poll `juju status` until all units are active/idle
- `<!-- test:run -->` — hidden commands (not rendered in docs)
- `<!-- test:assert -->` — hidden assertions
- `<!-- test:set-variables -->` — capture command output into shell variables
- `<!-- test:spread -->` — Spread task metadata (`priority`, `kill-timeout`)

**When editing tutorial pages:** preserve existing annotations, and use the
correct fence language (`` ```shell `` vs `` ```bash ``) intentionally.
