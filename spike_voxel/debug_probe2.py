"""Characterize the list-of-boolean setter limitation and find the workaround.

Tests, in order:
  A. create_entity with Voxels as python bools  -> expected FAIL (setter gap)
  B. create_entity with Voxels as 0/1 ints       -> coercion?
  C. author IfcVoxelGrid via STEP text + read    -> does file I/O support bool lists?
  D. RLE-as-integer payload (the real plan)       -> IfcIntegerVoxelData round-trip
"""
import os
import ifcopenshell
import ifcopenshell.express
import ifcopenshell.guid as guid

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED_EXP = os.path.join(HERE, "IFC4X4_TM27.exp")

schema = ifcopenshell.express.parse(MERGED_EXP)
ifcopenshell.register_schema(schema)
NAME = schema.schema.name()
print("schema:", NAME)


def mk_grid_kwargs():
    return dict(
        VoxelSizeX=1.0, VoxelSizeY=1.0, VoxelSizeZ=1.0,
        NumberOfVoxelsX=2, NumberOfVoxelsY=2, NumberOfVoxelsZ=1,
    )


# A. python bools
f = ifcopenshell.file(schema=NAME)
try:
    g = f.create_entity("IfcVoxelGrid", Voxels=[True, False, True, True], **mk_grid_kwargs())
    print("A bools: OK", g)
except Exception as e:
    print("A bools: FAIL —", type(e).__name__, str(e)[:90])

# B. ints 0/1
f = ifcopenshell.file(schema=NAME)
try:
    g = f.create_entity("IfcVoxelGrid", Voxels=[1, 0, 1, 1], **mk_grid_kwargs())
    print("B ints: OK", g)
except Exception as e:
    print("B ints: FAIL —", type(e).__name__, str(e)[:90])

# C. STEP text round-trip (bypasses the high-level setter entirely)
step = f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('','',(''),(''),'','','');
FILE_SCHEMA(('{NAME}'));
ENDSEC;
DATA;
#1=IFCVOXELGRID(1.,1.,1.,2,2,1,(.T.,.F.,.T.,.T.));
ENDSEC;
END-ISO-10303-21;
"""
try:
    f3 = ifcopenshell.file.from_string(step)
    g3 = f3.by_type("IfcVoxelGrid")[0]
    print("C STEP read: OK  Voxels =", list(g3.Voxels))
    # can we now WRITE it back out?
    out = os.path.join(HERE, "voxel_step_roundtrip.ifc")
    f3.write(out)
    f4 = ifcopenshell.open(out)
    print("C STEP write+reopen: OK  Voxels =", list(f4.by_type("IfcVoxelGrid")[0].Voxels))
except Exception as e:
    print("C STEP: FAIL —", type(e).__name__, str(e)[:120])

# D. RLE-as-integer payload — the encoding the Saikei plan uses anyway.
#    Dense mask [T,F,T,T] -> runs (T,1)(F,1)(T,2) -> flat [count,value,...] = [1,1,1,0,2,1]
f = ifcopenshell.file(schema=NAME)
try:
    g = f.create_entity("IfcVoxelGrid", Voxels=[1, 0, 1, 1], **mk_grid_kwargs())  # may fail; ignore
except Exception:
    g = None
try:
    rle = f.create_entity(
        "IfcIntegerVoxelData", GlobalId=guid.new(), Name="OccupancyRLE",
        ValueType="IfcInteger", ValueData=[1, 1, 1, 0, 2, 1],
    )
    out = os.path.join(HERE, "voxel_rle_int.ifc")
    f.write(out)
    f5 = ifcopenshell.open(out)
    print("D RLE-int payload round-trip: OK  ValueData =",
          list(f5.by_type("IfcIntegerVoxelData")[0].ValueData))
except Exception as e:
    print("D RLE-int: FAIL —", type(e).__name__, str(e)[:120])
