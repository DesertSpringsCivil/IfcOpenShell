"""Headless render of the voxel cut/fill preview, driven through the real
operator/core/tool stack. Produces spike_voxel/voxel_preview_cutfill.png.

  blender --background --python spike_voxel/render_voxel_preview.py
"""
import math

import bpy
import ifcopenshell
import ifcopenshell.guid

import bonsai.tool as tool

OUT = r"C:\GitHub\IfcOpenShell-saikei-dev\spike_voxel\voxel_preview_cutfill.png"


def build_production_model():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    project = f.create_entity("IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Demo")
    site = f.create_entity("IfcSite", GlobalId=ifcopenshell.guid.new(), Name="Site")
    f.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                    RelatingObject=project, RelatedObjects=[site])
    # Existing ground: flat at z=5. Design: tilted plane z = 2 + 0.6x (crosses existing).
    eg = [(0, 0, 5), (10, 0, 5), (10, 10, 5), (0, 10, 5)]
    dg = [(0, 0, 2), (10, 0, 8), (10, 10, 8), (0, 10, 2)]
    existing = tool.Surface.build_tin_from_points(name="Existing Ground", points=eg, kind="existing")
    tool.Surface.author_ifc_host(f, existing)
    tool.Surface.register(f, existing)
    design = tool.Surface.build_tin_from_points(name="Design Grade", points=dg, kind="proposed_group")
    tool.Surface.author_ifc_host(f, design)
    tool.Surface.register(f, design)
    return f, existing, design


def frame_and_render():
    # Bounds of the preview objects.
    objs = [o for o in bpy.data.objects if o.get("saikei_voxel_preview")]
    assert objs, "no voxel preview objects were created"
    import mathutils
    mins = mathutils.Vector((1e9, 1e9, 1e9))
    maxs = mathutils.Vector((-1e9, -1e9, -1e9))
    for o in objs:
        for v in o.bound_box:
            wv = o.matrix_world @ mathutils.Vector(v)
            mins = mathutils.Vector((min(mins[i], wv[i]) for i in range(3)))
            maxs = mathutils.Vector((max(maxs[i], wv[i]) for i in range(3)))
    center = (mins + maxs) / 2
    extent = (maxs - mins)
    radius = max(extent) or 10.0

    target = bpy.data.objects.new("VoxelAim", None)
    bpy.context.scene.collection.objects.link(target)
    target.location = center

    cam_data = bpy.data.cameras.new("VoxelCam")
    cam = bpy.data.objects.new("VoxelCam", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    d = radius * 2.4
    cam.location = center + mathutils.Vector((d * 0.9, -d * 1.1, d * 0.8))
    track = cam.constraints.new("TRACK_TO")
    track.target = target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"
    bpy.context.scene.camera = cam

    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(55), 0, math.radians(35))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "OBJECT"  # use obj.color (red cut / blue fill)
    scene.display.shading.show_cavity = True
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.render.filepath = OUT
    bpy.ops.render.render(write_still=True)
    print(f"__RENDERED__ {OUT}")


def main():
    # Ensure the Bonsai extension is enabled (it registers civil.* operators).
    try:
        bpy.ops.preferences.addon_enable(module="bl_ext.blender_org.bonsai")
    except Exception:
        pass

    f, existing, design = build_production_model()
    tool.Ifc.set(f)

    props = bpy.context.scene.CivilVoxelProperties
    props.existing_surface = existing.guid
    props.design_surface = design.guid
    props.cell_size = 0.5
    props.use_z_range = True
    props.z_min = 0.0
    props.z_max = 8.0

    result = bpy.ops.civil.voxel_preview_cut_fill()
    print(f"__OPERATOR__ {result}  cut={props.cut_volume:.1f} fill={props.fill_volume:.1f} net={props.net_volume:.1f}")
    frame_and_render()


main()
