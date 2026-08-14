# Bonsai (IfcOpenShell) — User-Flow Diagrams of Existing Tools

> Decision-oriented user flows for prominent **non-civil** Bonsai tools, built
> to compare interaction patterns against the Civil 3D alignment flows
> (`Civil3D_Alignment_UserFlows.md`). Grounded in the actual operators/panels
> in `src/bonsai/bonsai/bim/module/{model,type,drawing,project,spatial,sequence}`.
>
> **Color = interaction pattern** (not feature status), so you can see which
> patterns recur across Bonsai:
> 🟦 Entry point · 🟩 Modal viewport draw · 🟨 Enable→Edit→Finish param loop ·
> 🟪 List/panel CRUD · ⬜ Generate/export

---

## Recurring Bonsai interaction patterns (the cheat sheet)

Before the diagrams — four patterns show up over and over. Worth naming them,
because the Civil 3D comparison is really a comparison of *these*:

1. **🟦 Type-first authoring** — you pick/define a *Type* (IfcWallType…) before
   you place an *occurrence*. Geometry is an instance of a reusable type.
2. **🟩 Modal polyline draw** — a modal operator captures clicks in the viewport
   with hotkeys (F=flip, O=offset side), then commits geometry.
3. **🟨 Enable → Edit → Finish/Cancel** — the universal parametric edit loop.
   `enable_editing_X` (loads gizmos/panel) → edit → `finish_editing_X` (writes
   to IFC) or `cancel_editing_X` (revert). Doors, windows, stairs, roofs,
   railings, arrays, text — all identical.
4. **🟪 Panel list CRUD** — a panel holds a list (schedules, sheets, drawings,
   cost items, tasks, containers) with add/remove/load/expand buttons.

---

## 1. Geometry Authoring (model + type) — closest analog to alignment layout

```mermaid
flowchart TD
    Start([User wants to place building geometry]) --> Type{Type chosen?}
    Type -->|No| TM[Launch Type Manager<br/>bim.launch_type_manager]
    TM --> Pick[Browse / create type<br/>bim.set_active_type]
    Pick --> How
    Type -->|Yes| How{How to place it?}

    How -->|Sketch a path| Modal[Modal polyline draw]
    How -->|Single, at cursor| Occ[bim.add_occurrence<br/>choose rep: EMPTY / MESH / EXTRUSION]

    Modal --> MW[bim.draw_polyline_wall]
    Modal --> MS[bim.draw_polyline_slab]
    MW --> Hot["Viewport hotkeys:<br/>F = flip · O = cycle offset side<br/>RMB/Enter = commit"]
    MS --> Hot
    Hot --> Made
    Occ --> Made

    Made[Element placed] --> EditLoop{Refine}

    %% structural edits
    EditLoop -->|Topology| Topo["Align · Flip · Split · Merge ·<br/>Extend-to-wall · Offset"]
    %% parametric edits
    EditLoop -->|Dimensions| Param["change_extrusion_depth ·<br/>change_layer_length · x_angle"]
    %% profile edit
    EditLoop -->|Cross-section| Prof["enable_editing_extrusion_profile →<br/>edit 2D / CAD-sketcher → edit_extrusion_profile"]
    %% fill elements
    EditLoop -->|Add door/window| Fill["add_door / add_window →<br/>enable_editing → gizmos → finish_editing"]
    %% duplication
    EditLoop -->|Duplicate| Arr["add_array → enable_editing_array →<br/>edit_array → apply_array"]

    Topo --> Done
    Param --> Done
    Prof --> Done
    Fill --> Done
    Arr --> Done
    Done([Geometry authored → assign container, Psets, etc.])

    classDef entry fill:#0d47a1,stroke:#90caf9,color:#fff;
    classDef modal fill:#1b5e20,stroke:#a5d6a7,color:#fff;
    classDef param fill:#7c5c00,stroke:#ffe082,color:#fff;
    classDef crud fill:#4a148c,stroke:#ce93d8,color:#fff;

    class TM,Pick entry;
    class Modal,MW,MS,Hot modal;
    class Param,Prof,Fill,Arr,Occ param;
```

**Compare to Civil 3D:** the structure is strikingly close to the Alignment
Layout Tools flow — *choose a kind of thing → draw it interactively → enter an
edit loop*. Two big differences: (a) Bonsai is **type-first** (you instance a
reusable type; Civil 3D alignments are not type-based), and (b) Bonsai's
edit loop is the **Enable→Edit→Finish gizmo pattern** rather than C3D's
fixed/floating/free constraint solver. Bonsai has *no equivalent of the
constraint-based geometry model* — its parametrics are per-object, not
inter-entity tangency. That's the gap Saikei's PI editing already starts to
close on the civil side.

---

## 2. Drawing / Documentation — the deliverable workflow

```mermaid
flowchart TD
    Start([User has a 3D IFC model]) --> AddDrw[bim.add_drawing]
    AddDrw --> ViewType{View type}
    ViewType --> Plan[PLAN_VIEW]
    ViewType --> Sect[SECTION_VIEW]
    ViewType --> Elev[ELEVATION_VIEW]
    ViewType --> RCP[REFLECTED_PLAN]
    ViewType --> Mod[MODEL_VIEW]

    Plan --> Conf
    Sect --> Conf
    Elev --> Conf
    RCP --> Conf
    Mod --> Conf

    Conf[Configure in BIM_PT_camera:<br/>scale · underlay · linework · annotation · filters]
    Conf --> Lwk{Linework engine}
    Lwk -->|Precise HLR| OCC[OpenCascade]
    Lwk -->|Fast / artistic| FS[Freestyle]
    OCC --> Annot
    FS --> Annot

    Annot["Add annotations (Enable→Edit→Finish):<br/>TEXT · DIMENSION · LEADER · SYMBOL · LEVEL"]
    Annot --> Smart{Smart tags?}
    Smart -->|Yes| Prod["assign_selected_as_product →<br/>insert [Width] etc. dynamic values"]
    Smart -->|No| Gen
    Prod --> Gen

    Gen[bim.create_drawing<br/>renders underlay + linework + annotation → SVG]
    Gen --> Sheet{Put on a sheet?}
    Sheet -->|Yes| AddSheet[bim.add_sheet → add_drawing_to_sheet ·<br/>add_schedule_to_sheet · add_reference_to_sheet]
    AddSheet --> CreateSheets[bim.create_sheets → composed SVG]
    CreateSheets --> Export
    Sheet -->|No| Export
    Export{Export}
    Export --> DXF[convert_svg_to_dxf]
    Export --> PDF[open_sheet → print / PDF]
    DXF --> Done
    PDF --> Done
    Done([Documentation delivered])

    classDef entry fill:#0d47a1,stroke:#90caf9,color:#fff;
    classDef param fill:#7c5c00,stroke:#ffe082,color:#fff;
    classDef crud fill:#4a148c,stroke:#ce93d8,color:#fff;
    classDef gen fill:#37474f,stroke:#b0bec5,color:#fff;

    class AddDrw entry;
    class Annot,Prod param;
    class AddSheet,CreateSheets crud;
    class Gen,DXF,PDF,Export gen;
```

**Compare to Civil 3D:** this is Bonsai's analog to C3D's plan/profile sheet
production. Same shape: *define a view → configure → annotate → generate →
compose on sheet → export*. The annotation step reuses the Enable→Edit→Finish
pattern, and the dynamic-value tags (`[Width]`) mirror C3D's label expressions.

---

## 3. Project Setup + Spatial Structure — the "before you model" flow

```mermaid
flowchart TD
    Start([Launch Blender]) --> NewOrLoad{New or existing?}
    NewOrLoad -->|New| New[bim.new_project<br/>preset: metric_m / mm / imperial_ft / wizard]
    NewOrLoad -->|Existing| Load[bim.load_project → load_project_elements]

    New --> Wiz{Wizard?}
    Wiz -->|Yes| WizP[BIM_PT_new_project_wizard:<br/>schema · units · template]
    Wiz -->|No| Header
    WizP --> Create[bim.create_project]
    Create --> Header
    Load --> Header

    Header[Optional: edit_header<br/>author · org · MVD]
    Header --> Spatial[bim.import_spatial_decomposition<br/>open Spatial panel]

    Spatial --> Build{Build hierarchy<br/>panel list CRUD}
    Build --> Site[IfcSite]
    Build --> Bldg[IfcBuilding]
    Build --> Storey[IfcBuildingStorey × N]
    Build --> Space[IfcSpace]
    Site --> Default
    Bldg --> Default
    Storey --> Default
    Space --> Default

    Default[set_default_container]
    Default --> Assign[Model geometry →<br/>assign_container to place in storey]
    Assign --> Lib{Use library assets?}
    Lib -->|Yes| LibFlow[select_library_file → refresh_library →<br/>append_library_element]
    Lib -->|No| Save
    LibFlow --> Save
    Save([Ready to model · save_project])

    classDef entry fill:#0d47a1,stroke:#90caf9,color:#fff;
    classDef crud fill:#4a148c,stroke:#ce93d8,color:#fff;

    class New,Load,Create entry;
    class Build,Site,Bldg,Storey,Space,Default,Assign,LibFlow crud;
```

**Compare to Civil 3D:** C3D has no real equivalent of this spatial-container
setup — its "project" is a DWG with a drawing template, and elements live in a
flat object model, not an IfcSite→Building→Storey tree. This is a place where
Bonsai's IFC-native model is *richer* than C3D's, and it's the structure
Saikei's alignments/surfaces ultimately get parented into.

---

## 4. 4D Sequencing — a downstream data workflow

```mermaid
flowchart TD
    Start([User has a model]) --> AddWS[bim.add_work_schedule]
    AddWS --> Source{Build or import?}
    Source -->|Import| Imp[import_work_schedule_csv /<br/>import_p6 / import_msp]
    Source -->|Build| EditTasks[enable_editing_work_schedule_tasks]

    EditTasks --> Tree[add_summary_task → add_task<br/>hierarchical tree]
    Imp --> Time
    Tree --> Time

    Time[enable_editing_task_time:<br/>start / finish / duration · work_calendar]
    Time --> LinkProd[assign_product<br/>bind elements to task — ICOM Outputs]
    LinkProd --> Deps{Dependencies?}
    Deps -->|Yes| Seq[assign_predecessor / successor · lag]
    Deps -->|No| Status
    Seq --> Status

    Status[Optional: assign_status<br/>planned / in-progress / complete]
    Status --> Viz{Output}
    Viz --> Gantt[generate_gantt_chart]
    Viz --> Anim[BIM_PT_animation_tools →<br/>visualise_work_schedule_date_range = 4D]
    Gantt --> Loop
    Anim --> Loop
    Loop([Review → adjust dates/links → re-visualize])

    classDef entry fill:#0d47a1,stroke:#90caf9,color:#fff;
    classDef crud fill:#4a148c,stroke:#ce93d8,color:#fff;
    classDef param fill:#7c5c00,stroke:#ffe082,color:#fff;
    classDef gen fill:#37474f,stroke:#b0bec5,color:#fff;

    class AddWS entry;
    class Tree,Time,LinkProd,Seq,Status crud;
    class Gantt,Anim gen;
```

**Compare to Civil 3D:** the closest C3D analog is its data/quantity-takeoff
and material reporting, but C3D has no native 4D. This flow shows Bonsai's
**data-binding pattern** — author a structured list, then *assign model
elements to it* (task↔product). The same pattern drives the cost module
(cost-item↔quantity↔product). Civil deliverables (earthwork volumes, quantity
takeoff) would plug into exactly this binding model.

---

## 5. What this means for the Saikei comparison

| Pattern | Civil 3D alignment | Bonsai existing | Saikei today |
|---|---|---|---|
| Pick a kind of thing first | command per geometry type | **Type-first** (instance a Type) | command per op (PI method) |
| Interactive viewport draw | layout toolbar clicks | **Modal polyline** (F/O hotkeys) | PI picker (modal) ✅ |
| Parametric edit loop | fixed/floating/free constraints | **Enable→Edit→Finish gizmos** | PI grip edit (G key) ✅ |
| Tabular editor | Grid View / sub-entity | property panels + lists | ⬜ (gap) |
| List/CRUD management | Prospector tree | **Panel list CRUD** | partial |
| Data binding to model | quantity takeoff | **task/cost ↔ product** | earthwork Qto (one-way) |

**The actionable read:** if Saikei wants to feel native to Bonsai rather than
like a C3D port, the two patterns to lean into are **(1) the Enable→Edit→Finish
gizmo loop** (which Saikei's PI edit mode already echoes) and **(2) panel list
CRUD** for managing multiple alignments/profiles. Civil 3D's *fixed/floating/
free constraint model* has **no precedent anywhere in Bonsai** — so adopting it
would be net-new UX for the whole ecosystem. Worth flagging to Dion as a
deliberate choice: emulate C3D's constraint power, or stay with Bonsai's
lighter gizmo-based parametrics?

---

## Sources (Bonsai code, this repo)
- `src/bonsai/bonsai/bim/module/model/{operator,ui}.py`
- `src/bonsai/bonsai/bim/module/type/{operator,ui}.py`
- `src/bonsai/bonsai/bim/module/drawing/{operator,ui}.py`
- `src/bonsai/bonsai/bim/module/project/{operator,ui}.py`
- `src/bonsai/bonsai/bim/module/spatial/{operator,ui}.py`
- `src/bonsai/bonsai/bim/module/sequence/{operator,ui}.py`
