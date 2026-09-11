# Documentation agents guide

## Build

From the `docs/` directory:

```bash
make clean   # remove build artifacts and virtual environment
make run     # install dependencies, build, and serve with live reload at http://127.0.0.1:8000
```

## Auto-generated reference pages

Three reference pages are generated at build time from charm source files,
not hand-written:

| Page | Source file | Generator |
|------|-------------|-----------|
| `reference/_generated/actions.md` | `machine/actions.yaml` | `docs/_dev/generate_charm_reference.py` |
| `reference/_generated/configurations.md` | `machine/config.yaml` | `docs/_dev/generate_charm_reference.py` |
| `reference/_generated/statuses.md` | `common/single_kernel_kafka/core/literals.py` | `docs/_dev/generate_statuses.py` |

The `Status` enum in `literals.py` carries documentation prose
(`expectations`, `actions`) as fields on each `StatusLevel`. These
fields are not used at runtime — they exist solely to feed the statuses
reference page generator, which imports the enum directly. Members
with no `expectations` and no `actions` are automatically excluded from
the generated table.

Generated output lives in `docs/reference/_generated/` (gitignored).
The `make generate` target (also run automatically by `make html`,
`make run`, and `make pdf`) regenerates all pages.

Both generators use Jinja2 templates from `docs/_dev/templates/`
(`actions.md.j2`, `configurations.md.j2`, `statuses.md.j2`) to render
the Markdown output.  Edit the templates to change page layout; edit
the source files (or `StatusLevel` fields) to change content.

On Read the Docs, the `pre_build` job in `.readthedocs.yaml` runs the
generators before Sphinx. PR builds are only cancelled when no changes
affect `docs/`, `.readthedocs.yaml`, or the source files listed above.

## Agent-friendly docs (llms.txt)

The `sphinx-llm` extension generates `llms.txt`, `llms-full.txt`, and a
Markdown variant of every page (`<page>/index.html.md`). Three pieces of
configuration keep these discoverable and correct:

1. **`html_baseurl` must include the Read the Docs version segment.**
   Published docs are served under
   `https://canonical.com/data/kafka/docs/<version>/`. `conf.py` builds
   `html_baseurl` from `slug` and `version_slug`
   (`READTHEDOCS_VERSION`, defaulting to `local`). A trailing slash is
   required. Omitting either the version segment or the trailing slash
   makes every URL in `sitemap.xml` and `llms.txt` return 404.
2. **HTML directive** — `_templates/header.html` renders a
   visually-hidden `<div data-agent-directive>` pointing at `llms.txt`
   and explaining the `.md` URL convention. It is hidden with the
   clip-rect technique in `_static/agent-directive.css`, not
   `display: none`, so it stays in the accessibility tree.
3. **Markdown directive** — the `setup()` hook at the bottom of
   `conf.py` adds the same directive as a quoted block at the top of every
   generated `.md` file. This runs as a `build-finished` post-processing
   step (priority 900, after `sphinx-llm`) rather than via `source-read`,
   because `sphinx-llm` derives each `llms.txt` entry's title and
   fallback description from the first heading and paragraph of the
   generated Markdown — injecting into the sources would corrupt those
   descriptions.

To reproduce a production-like build locally:

```bash
READTHEDOCS=True READTHEDOCS_VERSION=4 READTHEDOCS_VERSION_TYPE=tag \
  READTHEDOCS_PROJECT=kafka READTHEDOCS_LANGUAGE=en \
  READTHEDOCS_GIT_IDENTIFIER=4 \
  READTHEDOCS_CANONICAL_URL=https://canonical.com/data/kafka/docs/4/ \
  make html
```

Audit the result with `npx afdocs check <url> --format scorecard`.

**Not fixable in this repository:** content negotiation for
`Accept: text/markdown` and cache-header lifetimes are handled by the
Canonical web platform / CDN in front of Read the Docs, not by Sphinx.

## Mermaid diagrams

Diagrams use the `{mermaid}` directive and are rendered live in the browser by
`sphinxcontrib-mermaid` (`raw` output mode).

Styling comes from the [Canonical Mermaid brand
kit](https://github.com/canonical/mermaid-brand-kit), following its
`docs/live-mermaid-in-sphinx.md` recipe, so design changes are picked up from
upstream rather than maintained here. Two generated artifacts are vendored into
`_static/` and must not be edited by hand — see `_static/VENDORED.md` for how to
update them:

| File | Role |
|------|------|
| `brand-theme.light.config.json` | Light palette, loaded into `mermaid_init_config` |
| `brand-theme.sphinx-dark.css` | Repaints diagrams for dark mode |

`_static/mermaid-brand-patch.css` holds the few local overrides the generated
artifacts cannot express (adapting the kit's assumed `#262626` page background to
Furo's `#131416`). Keep it minimal; each rule documents the upstream limitation
it works around, so it can be deleted when a newer kit release covers it.

Two upstream constraints are worth knowing about, both recorded in `conf.py`:

- The brand config requests the **ELK** renderer, but ELK flowcharts emit
  `aria-roledescription="flowchart-elk"` while the dark stylesheet only matches
  `flowchart-v2` and `sequence`. Left alone, dark mode silently does not apply to
  any flowchart. `conf.py` forces the dagre renderer as a workaround. This is a
  known upstream defect (blocker `B1` in the kit's own `AGENT-INBOX.md`).
- The dark stylesheet wins the cascade using `:is(#id, ...)` plus `:not(#guard)`
  to reach ID-level specificity. Local overrides must reproduce that idiom or
  they are silently ignored, `!important` notwithstanding.

**When authoring diagrams:** do not put `theme`, `themeVariables`, `themeCSS`,
`classDef`, `style`, or `linkStyle` in the Mermaid source — a per-diagram palette
drifts from the site theme and breaks dark mode. Semantic structure (subgraphs,
edge labels, `accTitle`/`accDescr`) is fine. The kit ships a lint for exactly
this, runnable from a kit checkout:

```bash
node scripts/audit-sphinx-adaptive-sources.mjs <path-to>/docs
```

**Verifying a change:** build, serve over HTTP, and compare computed styles in
both modes rather than trusting a screenshot — the page background can lag behind
a theme toggle and make a correct diagram look wrong:

```bash
make html && python3 -m http.server --directory _build 8000
```

Expected: nodes `#FFFFFF`/`#262626`, subgraphs `#F3F3F3`/`#3A3A3A`, ink
`#000000`/`#FFFFFF`, edge labels `#666666`/`#B3B3B3`, connectors `#E95420` in
both modes, and a transparent diagram canvas in dark mode.

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
Use `` ```bash `` for shell commands that should not be executed,
and use `` ```text `` for output examples.

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
