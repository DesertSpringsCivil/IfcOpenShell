"""Phase-0 voxel spike: prove IfcOpenShell can parse+register a 4.4-ish schema
carrying the TM27 voxel entities and author/round-trip a real IfcVoxelGrid.

Run with Blender's Python (has the compiled ifcopenshell wrapper):

  PY="/c/Program Files/Blender Foundation/Blender5/5.0/python/bin/python.exe"
  export PYTHONPATH="$APPDATA/Blender Foundation/Blender/5.0/extensions/.local/lib/python3.11/site-packages"
  "$PY" spike_voxel/voxel_spike.py

What it does:
  1. Merge a real IFC4X3_RC4 base .exp with a hand-authored TM27 entity delta
     (7 entities; all supertypes + value types already exist in 4.3) and patch
     the IfcProduct / IfcTessellatedItem SUPERTYPE OF (ONEOF ...) lists.
  2. ifcopenshell.express.parse() -> register_schema() the merged schema.
  3. Author IfcEarthworksCut hosting an IfcVoxelGrid (occupancy mask) + an
     IfcLabelVoxelData payload, linked via IfcRelAssignsToProduct.
  4. write() -> open() -> assert the mask + payload survive the round-trip.
  5. Preview the RLE value-add (dense vs run-length byte estimate) on a
     synthetic terrain-bounded mask.

Spike simplifications (NOT faithfulness blockers; noted for the report):
  - DERIVE attributes (GridSize, Values), WHERE rules, and the
    IfcListToExpandedArray FUNCTION are omitted. They neither serialize nor
    affect authoring; the real Phase-3 schema (built from the upstream XMI
    toolchain) carries them.
  - Base is IFC4X3_RC4 (the .exp present in the cloned repo); ADD2 vs RC4
    deltas are irrelevant to voxel authoring.

FINDINGS (for the forum / upstream):
  F1. TM27 declares `Voxels : ARRAY [1:?] OF IfcBoolean`. IfcOpenShell's express
      parser resolves an indeterminate-bound ARRAY [1:?] to UNKNOWN; LIST [1:?]
      parses cleanly. (A bounded ARRAY or LIST is more tool-friendly.)
  F2. IfcOpenShell's Python wrapper (0.8.4) has NO setter/getter for a
      list-of-boolean attribute — authoring AND reading the dense boolean
      occupancy mask both fail (no standard IFC entity has such an attribute, so
      it was never wired). The dense TM27 mask is therefore un-authorable through
      IfcOpenShell as-is. A list-of-INTEGER attribute round-trips perfectly.
  => CONVERGENCE: the RLE-as-integer encoding this project proposes (spec §3.3
     Option B) is not merely a size optimization — it is the only occupancy
     encoding that survives the current toolchain. This spike therefore carries
     occupancy as RLE integer run-pairs in `Voxels` (value 1=occupied, 0=empty),
     which IS the Saikei Option-B design, and round-trips it end to end.
"""

import os
import sys
import re
import struct

REPO = r"C:\GitHub\IFC4.x-development"
BASE_EXP = os.path.join(REPO, "reference_schemas", "IFC4x3_RC4.exp")
SCHEMA_NAME = "IFC4X4_TM27"
HERE = os.path.dirname(os.path.abspath(__file__))
MERGED_EXP = os.path.join(HERE, f"{SCHEMA_NAME}.exp")
OUT_IFC = os.path.join(HERE, "voxel_spike.ifc")

# --- TM27 entity delta (types/cardinalities per IFC44_Voxels_TM27_Reference.md) ---
TM27_DELTA = """
ENTITY IfcComplementaryData
 ABSTRACT SUPERTYPE OF (ONEOF
    (IfcVoxelData))
 SUBTYPE OF (IfcProduct);
END_ENTITY;

ENTITY IfcVoxelData
 ABSTRACT SUPERTYPE OF (ONEOF
    (IfcIntegerVoxelData
    ,IfcRealVoxelData
    ,IfcLabelVoxelData
    ,IfcLogicalVoxelData
    ,IfcVectorVoxelData))
 SUBTYPE OF (IfcComplementaryData);
\tValueType : OPTIONAL IfcLabel;
END_ENTITY;

ENTITY IfcIntegerVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcInteger;
\tUnit : OPTIONAL IfcUnit;
END_ENTITY;

ENTITY IfcRealVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcReal;
\tUnit : OPTIONAL IfcUnit;
END_ENTITY;

ENTITY IfcLabelVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcLabel;
END_ENTITY;

ENTITY IfcLogicalVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcLogical;
END_ENTITY;

ENTITY IfcVectorVoxelData
 SUBTYPE OF (IfcVoxelData);
\tValueData : LIST [1:?] OF IfcVector;
\tUnit : OPTIONAL IfcUnit;
END_ENTITY;

ENTITY IfcVoxelGrid
 SUBTYPE OF (IfcTessellatedItem);
\tVoxelSizeX : IfcNonNegativeLengthMeasure;
\tVoxelSizeY : IfcNonNegativeLengthMeasure;
\tVoxelSizeZ : IfcNonNegativeLengthMeasure;
\tNumberOfVoxelsX : IfcPositiveInteger;
\tNumberOfVoxelsY : IfcPositiveInteger;
\tNumberOfVoxelsZ : IfcPositiveInteger;
\tVoxels : LIST [1:?] OF IfcInteger;
END_ENTITY;
"""


def build_merged_exp():
    with open(BASE_EXP, "r", encoding="utf-8") as fh:
        src = fh.read()

    # 1. Rename the schema (first `SCHEMA <name>;`).
    src, n = re.subn(r"SCHEMA\s+\w+\s*;", f"SCHEMA {SCHEMA_NAME};", src, count=1)
    assert n == 1, "could not find SCHEMA header line"

    # 2. Admit IfcComplementaryData under IfcProduct's ONEOF.
    needle = ",IfcStructuralItem))\n SUBTYPE OF (IfcObject);"
    repl = ",IfcStructuralItem\n    ,IfcComplementaryData))\n SUBTYPE OF (IfcObject);"
    assert src.count(needle) == 1, "IfcProduct ONEOF anchor not unique/found"
    src = src.replace(needle, repl)

    # 3. Admit IfcVoxelGrid under IfcTessellatedItem's ONEOF.
    needle = ",IfcTessellatedFaceSet))\n SUBTYPE OF (IfcGeometricRepresentationItem);"
    repl = ",IfcTessellatedFaceSet\n    ,IfcVoxelGrid))\n SUBTYPE OF (IfcGeometricRepresentationItem);"
    assert src.count(needle) == 1, "IfcTessellatedItem ONEOF anchor not unique/found"
    src = src.replace(needle, repl)

    # 4. Insert the entity delta just before END_SCHEMA.
    head, sep, tail = src.rpartition("END_SCHEMA;")
    assert sep, "no END_SCHEMA; in base exp"
    src = head + TM27_DELTA + "\n" + sep + tail

    with open(MERGED_EXP, "w", encoding="utf-8") as fh:
        fh.write(src)
    print(f"[1] merged exp written: {MERGED_EXP} ({len(src):,} bytes)")


def rle_encode(seq):
    from itertools import groupby
    return [(v, sum(1 for _ in g)) for v, g in groupby(seq)]


def rle_flatten(runs):
    flat = []
    for val, count in runs:
        flat.extend([count, val])  # (count, value) ordering per spec §9 open-q
    return flat


def rle_decode_flat(flat):
    out = []
    for i in range(0, len(flat), 2):
        out.extend([flat[i + 1]] * flat[i])
    return out


def author_and_roundtrip():
    import ifcopenshell
    import ifcopenshell.express
    import ifcopenshell.guid as guid

    print("[2] parsing merged exp (full schema, may take a bit)...")
    schema = ifcopenshell.express.parse(MERGED_EXP)
    ifcopenshell.register_schema(schema)
    name = schema.schema.name()
    print(f"    registered schema: {name}")

    f = ifcopenshell.file(schema=name)
    f.create_entity("IfcProject", GlobalId=guid.new(), Name="Voxel Spike")
    pt = f.create_entity("IfcCartesianPoint", Coordinates=(0.0, 0.0, 0.0))
    axis = f.create_entity("IfcAxis2Placement3D", Location=pt)
    ctx = f.create_entity(
        "IfcGeometricRepresentationContext",
        ContextType="Model",
        CoordinateSpaceDimension=3,
        Precision=1e-5,
        WorldCoordinateSystem=axis,
    )

    # 2x2x1 grid; occupancy mask over canonical X->Y->Z order.
    # Stored as RLE integer run-pairs (Saikei Option-B encoding): 1=occupied.
    mask = [1, 0, 1, 1]
    voxels_rle = rle_flatten(rle_encode(mask))  # -> [1,1, 1,0, 2,1]
    grid = f.create_entity(
        "IfcVoxelGrid",
        VoxelSizeX=1.0, VoxelSizeY=1.0, VoxelSizeZ=1.0,
        NumberOfVoxelsX=2, NumberOfVoxelsY=2, NumberOfVoxelsZ=1,
        Voxels=voxels_rle,
    )
    shaperep = f.create_entity(
        "IfcShapeRepresentation",
        ContextOfItems=ctx,
        RepresentationIdentifier="Body",
        RepresentationType="Tessellation",
        Items=[grid],
    )
    pds = f.create_entity("IfcProductDefinitionShape", Representations=[shaperep])

    cut = f.create_entity(
        "IfcEarthworksCut", GlobalId=guid.new(), Name="Spike Cut",
        Representation=pds,
    )

    # Semantic layers, one IfcVoxelData per attribute (gathered to occupied cells).
    # 3 occupied cells -> 3 values each.
    material = f.create_entity(
        "IfcLabelVoxelData", GlobalId=guid.new(), Name="Material",
        Representation=pds, ValueType="IfcLabel", ValueData=["sand", "clay", "sand"],
    )
    confidence = f.create_entity(
        "IfcRealVoxelData", GlobalId=guid.new(), Name="Confidence",
        Representation=pds, ValueType="IfcReal", ValueData=[0.9, 0.7, 0.95],
    )
    f.create_entity(
        "IfcRelAssignsToProduct", GlobalId=guid.new(),
        RelatedObjects=[material, confidence], RelatingProduct=cut,
    )

    f.write(OUT_IFC)
    print(f"[3] authored + wrote {OUT_IFC} ({os.path.getsize(OUT_IFC):,} bytes)")

    # Round-trip in the same process (schema already registered).
    f2 = ifcopenshell.open(OUT_IFC)
    g2 = f2.by_type("IfcVoxelGrid")[0]
    mat2 = f2.by_type("IfcLabelVoxelData")[0]
    conf2 = f2.by_type("IfcRealVoxelData")[0]
    cut2 = f2.by_type("IfcEarthworksCut")[0]

    assert rle_decode_flat(list(g2.Voxels)) == mask, ("mask mismatch", list(g2.Voxels))
    assert (g2.NumberOfVoxelsX, g2.NumberOfVoxelsY, g2.NumberOfVoxelsZ) == (2, 2, 1)
    assert list(mat2.ValueData) == ["sand", "clay", "sand"], list(mat2.ValueData)
    assert list(conf2.ValueData) == [0.9, 0.7, 0.95], list(conf2.ValueData)
    assert cut2.ReferencedBy, "IfcRelAssignsToProduct missing"
    print("[4] round-trip OK: RLE occupancy decodes to mask; label + real layers "
          "and product assignment all survived")
    print(f"    file schema: {f2.schema}; occupied cells = {sum(mask)}")


def rle_preview():
    """Preview the Saikei RLE value-add on a synthetic terrain-bounded mask."""
    from itertools import groupby
    # 200x200x50 = 2,000,000 cells; bottom ~60% full (terrain below a surface).
    nx, ny, nz = 200, 200, 50
    mask = []
    for k in range(nz):
        full = k < int(nz * 0.6)
        mask.extend([full] * (nx * ny))
    runs = [(v, sum(1 for _ in g)) for v, g in groupby(mask)]
    dense_bytes = len(mask) // 8  # 1 bit/cell packed
    rle_bytes = len(runs) * (1 + 8)  # value byte + 8-byte count, generous
    print(f"[5] RLE preview on {len(mask):,}-cell mask: "
          f"{len(runs)} runs; dense~{dense_bytes:,}B vs RLE~{rle_bytes:,}B "
          f"({dense_bytes / max(rle_bytes,1):,.0f}x)")


if __name__ == "__main__":
    build_merged_exp()
    author_and_roundtrip()
    rle_preview()
    print("\nSPIKE RESULT: GO")
