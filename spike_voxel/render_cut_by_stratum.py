"""Headless render of excavation-by-stratum via the real operator.
Produces spike_voxel/voxel_preview_cut_by_stratum.png.

  blender --background --python spike_voxel/render_cut_by_stratum.py
"""
import math

import bpy
import ifcopenshell
import ifcopenshell.guid
import mathutils

import bonsai.tool as tool

OUT = r"C:\GitHub\IfcOpenShell-saikei-dev\spike_voxel\voxel_preview_cut_by_stratum.png"


def build():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Demo")
    site = f.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                    RelatingObject=project, RelatedObjects=[site])
    # Stratum boundaries (terrains): clay top z8, sand top z6, bedrock z2.
    terr = {
        "Top of Clay": [(0, 0, 8), (10, 0, 8.4), (10, 10, 7.6), (0, 10, 8)],
        "Top of Sand": [(0, 0, 6), (10, 0, 6.3), (10, 10, 5.7), (0, 10, 6)],
        "Bedrock": [(0, 0, 2), (10, 0, 2), (10, 10, 2), (0, 10, 2)],
    }
    guids = {}
    for name, pts in terr.items():
        s = tool.Surface.build_tin_from_points(name=name, points=pts, kind="existing")
        tool.Surface.author_ifc_host(f, s)
        tool.Surface.register(f, s)
        guids[name] = s.guid
    # Design grade (fill): excavate down to z4 (cuts through clay + sand).
    dg = [(0, 0, 4), (10, 0, 4), (10, 10, 4), (0, 10, 4)]
    design = tool.Surface.build_tin_from_points(name="Design Grade", points=dg, kind="proposed_group")
    tool.Surface.author_ifc_host(f, design)
    tool.Surface.register(f, design)
    guids["Design Grade"] = design.guid
    return f, guids


def render():
    objs = [o for o in bpy.data.objects if o.get("saikei_voxel_preview")]
    assert objs, "no preview objects"
    mn = mathutils.Vector((1e9,) * 3)
    mx = mathutils.Vector((-1e9,) * 3)
    for o in objs:
        for v in o.bound_box:
            wv = o.matrix_world @ mathutils.Vector(v)
            mn = mathutils.Vector((min(mn[i], wv[i]) for i in range(3)))
            mx = mathutils.Vector((max(mx[i], wv[i]) for i in range(3)))
    center = (mn + mx) / 2
    radius = max(mx - mn) or 10.0
    aim = bpy.data.objects.new("Aim", None)
    bpy.context.scene.collection.objects.link(aim)
    aim.location = center
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.scene.collection.objects.link(cam)
    d = radius * 2.4
    cam.location = center + mathutils.Vector((d * 0.9, -d * 1.1, d * 0.7))
    c = cam.constraints.new("TRACK_TO")
    c.target = aim
    c.track_axis = "TRACK_NEGATIVE_Z"
    c.up_axis = "UP_Y"
    bpy.context.scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(55), 0, math.radians(35))
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.display.shading.color_type = "OBJECT"
    sc.display.shading.show_cavity = True
    sc.render.resolution_x = 1400
    sc.render.resolution_y = 1000
    sc.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print(f"__RENDERED__ {OUT}")


def main():
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
    except Exception:
        pass
    f, guids = build()
    tool.Ifc.set(f)
    props = bpy.context.scene.CivilVoxelProperties
    props.existing_surface = guids["Top of Clay"]   # top boundary / existing ground
    props.design_surface = guids["Design Grade"]
    props.cell_size = 0.5
    result = bpy.ops.civil.voxel_cut_by_stratum()
    print(f"__OPERATOR__ {result}  cut_strata={[(i.name, round(i.volume,1)) for i in props.cut_strata]}")
    render()


main()
