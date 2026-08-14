# Saikei Civil — Codespaces / Dev Container

Provisions a cloud dev environment for the Saikei civil module (Bonsai /
IfcOpenShell). Two tiers, because the two test layers have very different
requirements.

## What you get

| Tier | Covers | Reliability |
|------|--------|-------------|
| **1 — pure Python** (always) | `test/core/*`, pure-math `test/tool/*` via `-p no:pytest-blender` | Solid |
| **2 — Blender headless** (opt-in) | `bpy`-dependent tool + operator tests | Best-effort |

Tier 1 installs `ifcopenshell` (Linux wheel, includes the alignment API and a
compiled wrapper), `shapely`/`numpy`/`lark`, and pytest, and puts the in-repo
`bonsai` package on `PYTHONPATH`.

## Quick start

After the codespace finishes building, from the repo root:

```bash
cd src/bonsai
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest test/core -o "addopts=" -p no:pytest-blender -v
```

## Enabling Blender (Tier 2)

Tool/operator tests need Blender's bundled Python. It's off by default to keep
first-build fast. To enable:

- **Persistent:** set `SAIKEI_INSTALL_BLENDER` to `"1"` in
  [devcontainer.json](devcontainer.json) `containerEnv` (or as a Codespaces
  secret) and **Rebuild Container**.
- **One-off in a running codespace:**
  ```bash
  SAIKEI_INSTALL_BLENDER=1 bash .devcontainer/setup.sh
  ```

`BLENDER_VERSION` (default `5.0.0`) controls which build is downloaded from
`download.blender.org`. If the download 404s, point it at a version that
actually exists for linux-x64.

## Known caveats

- **ifcopenshell version drift.** The repo bundles its own ifcopenshell source
  at `src/ifcopenshell-python` (VERSION `0.8.5`), but only with a **Windows**
  compiled wrapper. The codespace uses the pip Linux build instead. If the pip
  release lags the repo and lacks `ifcopenshell.api.alignment`, setup.sh retries
  with a pre-release wheel and warns if it still can't import it.
- **Tier 2 is unverified across Blender point releases.** The 5.x download URL
  pattern and headless GL libs are best-effort; expect to iterate on first run.
- This is a fork of a large monorepo. Keep all customization inside
  `.devcontainer/` so it doesn't conflict on `git rebase upstream/saikei`.
