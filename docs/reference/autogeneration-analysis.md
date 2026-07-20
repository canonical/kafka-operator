---
orphan: true
myst:
  html_meta:
    description: "Analysis of two approaches for generating Charmhub-style reference pages (Actions, Configurations, Libraries) from local charm files."
---

(reference-autogeneration-analysis)=
# Auto-generating reference pages: approach analysis

This page documents two approaches for generating the **Actions**, **Configurations**, and **Libraries** reference pages locally (instead of linking to `charmhub.io`), and recommends one.

The source data lives in the charm directories:

| Page | Source file(s) |
|---|---|
| Actions | `actions.yaml` |
| Configurations | `config.yaml` |
| Libraries | `lib/charms/<charm>/v<N>/*.py` (docstrings + `LIBID`/`LIBAPI`/`LIBPATCH`) |

---

## Approach 1 — Web scraping Charmhub pages

A script fetches `https://charmhub.io/kafka/actions`, `/configure`, `/libraries/...` at build time, parses the rendered HTML, and emits Markdown.

```text
flowchart LR
  R["Charmhub.io<br/>HTML pages"] --> F["HTTP fetch<br/>+ HTML parser"]
  F --> P["Strip nav/footer/<br/>cookie banners"]
  P --> O["docs/reference/_generated/<br/>*.md"]
  O --> S["Sphinx build"]
  S --> H["Published docs"]
```

**Pros**
- Reproduces exactly what is on Charmhub, including orphaned libraries

**Cons**
- Requires network access at build time (breaks offline / restricted CI)
- Non-reproducible: same commit → different docs depending on what is promoted to `4/stable` at build time
- Fragile: any Charmhub HTML/template change silently breaks the scraper
- Slow (multiple HTTP fetches per build)
- Duplicates logic Charmhub already applies to the same YAML we have locally

---

## Approach 2 — Generate from local files

A small Python script (`docs/_dev/generate_charm_reference.py`) parses the YAML and `.py` files in the repo and emits Markdown. The source files are already structured (YAML + Python docstrings), so no HTML scraping is needed.

```text
flowchart LR
  A["actions.yaml<br/>config.yaml<br/>lib/charms/**/*.py"] --> G["Generator script<br/>pyyaml + ast"]
  G --> O["docs/reference/_generated/<br/>actions.md<br/>configurations.md<br/>libraries.md"]
  O --> S["Sphinx build"]
  S --> H["Published docs"]
```

**Pros**
- Deterministic, offline, sub-second
- Docs at commit X reflect the charm at commit X
- No network dependency in CI
- No drift possible by construction

**Cons**
- Does not reproduce orphaned libraries on Charmhub (e.g. `kafka_libs`, `kafka_snap` — published once in 2022, no longer in the repo). This is arguably correct behaviour.

### Output handling: committed vs. build-time

Once Approach 2 is chosen, there is a second decision: **commit the generated Markdown to the repo and verify with CI, or generate at build time and gitignore the output.**

#### Option A — Commit generated files + CI drift check

The generator runs in CI on every PR, regenerates the `.md` files, and fails the check if the committed files differ from the freshly generated ones.

```text
flowchart LR
  PR["PR opened"] --> G["CI: run generator"]
  G --> D["Diff vs. committed .md"]
  D -->|drift| F["CI fails<br/>contributor must regen + commit"]
  D -->|match| P["CI passes"]
```

**Pros**
- Generated content is reviewable in PR diffs
- Output available without running the generator

**Cons**
- PR noise: every `config.yaml` edit produces a second noisy diff in generated `.md`
- Merge conflicts on generated files even when actual changes don't overlap
- Friction: contributors must learn the regen command for a one-line YAML change
- Two sources of truth (YAML + committed `.md`); the CI check exists only to paper over drift
- Stale content on old tags if someone forgot to regen before tagging

#### Option B — Build-time generation, gitignored output

The generator runs as a pre-build step in `docs/Makefile`; output lives in a gitignored `docs/reference/_generated/` and is never committed.

```text
flowchart LR
  S["Source YAML + .py"] --> G["Makefile pre-build:<br/>run generator"]
  G --> O["_generated/*.md<br/>gitignored"]
  O --> SP["Sphinx build"]
  SP --> H["Published docs"]
```

**Pros**
- Zero drift by construction — impossible for output to lag source
- No PR noise; only source YAML appears in diffs
- No CI check workflow to maintain
- Correct on old tags: checking out `v4.0` and building yields docs matching `v4.0`'s YAML
- No merge conflicts on generated files

**Cons**
- Generated content not visible in PR diff (but it's deterministic from the YAML, which is visible)
- Adds a few milliseconds to each docs build (negligible)

---

## Recommendation

**Approach 2, Option B** — generate from local files at build time, gitignore the output.

- **Approach 2 over Approach 1:** the source files are already structured (YAML + Python docstrings), the generator is fast and deterministic, and the only "loss" — orphaned 2022 libraries marked "Do not use." — is content that should not be documented anyway. Approach 1 trades a clean local pipeline for a fragile network round-trip through HTML, for no information gain.
- **Option B over Option A:** the generator is fast, deterministic, and offline — the conditions under which commit-and-check is the wrong tradeoff. Option A is justified only when the generator is slow, needs network/credentials, or its output is consumed outside the docs build. None apply here. The existing docs CI build already catches real failures (malformed YAML, missing library files) as a side effect of building, so no extra drift-check workflow is needed.

---

## Implementation notes

- Output directory `docs/reference/_generated/` is added to `.gitignore` — generated files are never committed.
- No CI drift-check workflow is needed: the existing docs CI build fails loudly if the YAML is malformed or a referenced library is missing.
- The `index.md` toctree points at `_generated/actions.md`, `_generated/configurations.md`, `_generated/libraries.md`.
- Both `machine/` and `k8s/` charms can be documented from their respective YAML files.
