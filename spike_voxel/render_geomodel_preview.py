"""Headless render of the voxel geomodel/strata preview via the real operator.
Produces spike_voxel/voxel_preview_geomodel.png.

  blender --background --python spike_voxel/render_geomodel_preview.py
"""
import math

import bpy
import ifcopenshell
import ifcopenshell.guid
import mathutils

import bonsai.tool as tool

OUT = r"C:\GitHub\IfcOpenShell-saikei-dev\spike_voxel\voxel_preview_geomodel.png"


def build_production_model():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Demo")
    site = f.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                    RelatingObject=project, RelatedObjects=[site])
    # Three gently-tilted stratigraphic boundaries (top -> bottom).
    boundaries = {
        "Top of Clay": [(0, 0, 8), (10, 0, 8.5), (10, 10, 7.5), (0, 10, 8)],
        "Top of Sand": [(0, 0, 5), (10, 0, 5.5), (10, 10, 4.5), (0, 10, 5)],
        "Bedrock": [(0, 0, 2), (10, 0, 2.2), (10, 10, 1.8), (0, 10, 2)],
    }
    for name, pts in boundaries.items():
        s = tool.Surface.build_tin_from_points(name=name, points=pts, kind="existing")
        tool.Surface.author_ifc_host(f, s)
        tool.Surface.register(f, s)
    return f


def frame_and_render():
    objs = [o for o in bpy.data.objects if o.get("saikei_voxel_preview")]
    assert objs, "no voxel preview objects were created"
    mins = mathutils.Vector((1e9, 1e9, 1e9))
    maxs = mathutils.Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for v in o.bound_box:
            wv = o.matrix_world @ mathutils.Vector(v)
            mins = mathutils.Vector((min(mins[i], wv[i]) for i in range(3)))
            maxs = mathutils.Vector((max(maxs[i], wv[i]) for i in range(3)))
    center = (mins + maxs) / 2
    radius = max(maxs - mins) or 10.0

    target = bpy.data.objects.new("Aim", None)
    bpy.context.scene.collection.objects.link(target)
    target.location = center
    cam = bpy.data.objects.new("Cam", bpy.data.cameras.new("Cam"))
    bpy.context.scene.collection.objects.link(cam)
    d = radius * 2.4
    cam.location = center + mathutils.Vector((d * 0.9, -d * 1.1, d * 0.7))
    t = cam.constraints.new("TRACK_TO")
    t.target = target
    t.track_axis = "TRACK_NEGATIVE_Z"
    t.up_axis = "UP_Y"
    bpy.context.scene.camera = cam
    sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(55), 0, math.radians(35))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print(f"__RENDERED__ {OUT}")


def main():
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
    except Exception:
        pass
    f = build_production_model()
    tool.Ifc.set(f)
    props = bpy.context.scene.CivilVoxelProperties
    props.cell_size = 0.5
    result = bpy.ops.civil.voxel_preview_geomodel()
    print(f"__OPERATOR__ {result}  strata={[(i.name, round(i.volume, 1)) for i in props.strata]}")
    frame_and_render()


main()
