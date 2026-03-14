# Saikei Civil — Claude Code Agent Team Plan (v2)

**Updated:** March 10, 2026  
**Based on:** `saikei-project-summary.md` (Claude Code analysis of actual codebase)

---

## Current Reality

Saikei is merged into Bonsai in the IfcOpenShell repo (`branch: saikei`). Code lives at `src/bonsai/bonsai/`. It follows Bonsai's 3-layer architecture with `CIVIL_*` prefixes.

**What exists:** Horizontal alignment (PI method), segment visualization, PI picker, PI edit mode, georef support, CSV import, stationing, Add Element dialog integration. Core is ~185 lines, Tool is ~1,138 lines, UI is ~41K.

**What doesn't exist yet:** Vertical alignment, corridor generation, cross-sections, earthwork, drainage, and — critically — **zero tests**.

---

## The Agent Team (6 Agents)

| Agent | Model | Role | When to Use |
|-------|-------|------|-------------|
| `saikei-architect` | Opus | Architecture guardian | Code review, "does this go in core or tool?", refactoring |
| `saikei-ifc` | Sonnet | IFC 4.3 specialist | IFC entities, validation errors, schema questions |
| `saikei-tool-dev` | Sonnet | Tool layer engineer | Math, geometry, IFC ops, Blender objects — the workhorse |
| `saikei-blender-ui` | Sonnet | UI/Operator developer | Operators, panels, props, decorators, modals |
| `saikei-tester` | Haiku | Test engineer | Writing tests, fixtures, test infrastructure |
| `saikei-docs` | Sonnet | Documentation | Guides, changelog, grants, community content |

---

## Installation

Copy into your dev fork working copy:

```
C:\GitHub\IfcOpenShell-saikei-dev\
├── CLAUDE.md
└── .claude/
    └── agents/
        ├── saikei-architect.md
        ├── saikei-ifc.md
        ├── saikei-tool-dev.md
        ├── saikei-blender-ui.md
        ├── saikei-tester.md
        └── saikei-docs.md
```

These go in the repo root, NOT inside `src/bonsai/`. Claude Code reads them from wherever you open the terminal.

Note: The `.claude/` folder and `CLAUDE.md` are for your dev fork only. Don't include them in PRs to Dion — add them to `.gitignore` or keep them on `saikei-dev` only.

---

## Git Workflow

```
IfcOpenShell/IfcOpenShell (upstream — Dion's repo)
  └── branch: saikei ← clean PRs, ≤4,000 lines each
        ↑
        │  squashed, curated PRs
        │
desertspringscivil/IfcOpenShell (your fork)
  └── branch: saikei-dev ← agents work here freely
```

### Local Setup

```
C:\GitHub\
├── IfcOpenShell\          ← Dion's repo (optional, for reference)
└── IfcOpenShell-saikei-dev\      ← Your fork — agents work here
```

```bash
# One-time setup
git clone https://github.com/desertspringscivil/IfcOpenShell.git IfcOpenShell-saikei-dev
cd IfcOpenShell-saikei-dev
git remote add upstream https://github.com/IfcOpenShell/IfcOpenShell.git
git fetch upstream
git checkout -b saikei-dev upstream/saikei
```

### Daily: Agents Work on saikei-dev
No restrictions. Agents commit freely. Messy history is fine here.

### When Ready for Dion's Review
```bash
# Create a clean review branch
git checkout -b vertical-alignment-for-review saikei-dev

# Squash agent commits into clean, ≤4,000-line chunks
git rebase -i upstream/saikei

# Push and PR against upstream/saikei
git push origin vertical-alignment-for-review
# → Create PR on GitHub: desertspringscivil:vertical-alignment-for-review → IfcOpenShell:saikei
```

### Staying in Sync with Dion
```bash
git fetch upstream
git checkout saikei-dev
git rebase upstream/saikei
```

---

## Workflow

### Daily (15-30 min)
1. Open Claude Code in the repo
2. Give a task: "Add vertical alignment support to tool/alignment.py"
3. Claude auto-delegates to the right agent(s)
4. Review output, approve or iterate

### Weekly (1-2 hours)
1. Review code changes
2. Run tests (once they exist)
3. Check architecture compliance
4. Update task list

### Good Agent Tasks (Single Session)

- "Write core tests for enter_pi_edit_mode and exit_pi_edit_mode"
- "Add IfcAlignmentVertical support to tool/alignment.py with CONSTANTGRADIENT and PARABOLICARC segment types"
- "Create CIVIL_OT_add_pvi operator and CIVIL_PT_vertical_editor panel"
- "Review tool/alignment.py for any architecture violations"
- "Update the README with current feature list"

### Bad Agent Tasks (Too Vague)

- "Build vertical alignment" (break it into core/tool/ui tasks)
- "Make Saikei better"
- "Refactor everything"

---

## Priority Task Backlog

### Immediate Priority: Tests (saikei-tester)
No tests exist. This is the biggest risk for agent-driven development — agents can't verify they haven't broken anything.

- [ ] Create `test/core/test_alignment.py` — mock-based tests for business logic
- [ ] Create `test/tool/test_alignment.py` — geometry math tests
- [ ] Create IFC integration test fixtures
- [ ] Verify test infrastructure works with Bonsai's pytest setup

### Next: Vertical Alignment
- [ ] Add vertical geometry math to `tool/alignment.py` (tool-dev)
- [ ] Add vertical business logic to `core/alignment.py` (tool-dev + architect review)
- [ ] Create `CIVIL_OT_add_pvi`, `CIVIL_PT_vertical_editor` (blender-ui)
- [ ] IFC entities: IfcAlignmentVertical, IfcAlignmentVerticalSegment (ifc)
- [ ] Tests for vertical alignment (tester)

### Then: Corridor Generation
- [ ] Research: map corridor concepts to current Bonsai patterns (ifc)
- [ ] Cross-section profiles: IfcOpenCrossProfileDef (ifc + tool-dev)
- [ ] Corridor solid: IfcSectionedSolidHorizontal (ifc + tool-dev)
- [ ] Corridor UI: operators, panels (blender-ui)
- [ ] Tests (tester)

### Future
- Earthwork calculations (cut/fill volumes)
- Drainage design
- Spiral transitions (IfcClothoid)
- LandXML import/export
- Superelevation

---

## Key References (Project Knowledge)

| Document | What It Contains |
|----------|-----------------|
| `saikei-project-summary.md` | **Canonical reference** — current codebase API, architecture, patterns |
| `1_Introduction.md` through `9_Precision_and_Tolerance.md` | IFC 4.3 alignment specification |
| `Corridor_Generation_Deep_Research.md` | Civil 3D/OpenRoads/IFC corridor patterns |
| `IFC_Roadway_Templates_Assemblies_Reference.md` | Cross-section template reference |
| `IFC_Relationships_Analysis.md` | IFC relationship patterns |
| `IFC_Alignment_API_Comparison.docx` | Rick Brice collaboration context |
| `saikei-civil-brand-package.md` | Brand identity and positioning |
| `IRROADWP3...InstanceDiagrams.pdf` | buildingSMART instance diagrams |
