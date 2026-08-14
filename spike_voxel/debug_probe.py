"""Introspect how the registered IFC4X4_TM27 schema typed IfcVoxelGrid.Voxels,
and whether aggregate attributes work at all in a runtime-registered schema."""
import os
import ifcopenshell
import ifcopenshell.express

HERE = os.path.dirname(os.path.abspath(__file__))
MERGED_EXP = os.path.join(HERE, "IFC4X4_TM27.exp")

schema = ifcopenshell.express.parse(MERGED_EXP)  # fast from cache
ifcopenshell.register_schema(schema)
name = schema.schema.name()
print("schema:", name)

decl = schema.schema.declaration_by_name("IfcVoxelGrid")
print("IfcVoxelGrid attrs:")
for a in decl.all_attributes():
    ty = a.type_of_attribute()
    print(f"  {a.name():20s} -> {ty}  (str={ty.declared_type() if hasattr(ty,'declared_type') else '?'})")

# Does an existing aggregate-of-simple-type entity work in this schema?
f = ifcopenshell.file(schema=name)
try:
    cpl = f.create_entity("IfcCartesianPointList3D", CoordList=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)])
    print("IfcCartesianPointList3D OK:", cpl)
except Exception as e:
    print("IfcCartesianPointList3D FAIL:", e)

# Compare against the built-in IFC4X3_ADD2 schema's IfcVoxelGrid? (won't exist)
# Instead, inspect a known LIST-OF-boolean-free entity that uses LIST OF measure.
try:
    face = f.create_entity("IfcIndexedPolygonalFace", CoordIndex=[1, 2, 3])
    print("IfcIndexedPolygonalFace (LIST OF int) OK:", face)
except Exception as e:
    print("IfcIndexedPolygonalFace FAIL:", e)
