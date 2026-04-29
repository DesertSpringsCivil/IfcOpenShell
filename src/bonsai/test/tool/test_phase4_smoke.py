def test_blender_python_works():
    import bpy
    assert bpy.app.version >= (5, 0, 0)

def test_ifcopenshell_api_surface_imports():
    import ifcopenshell.api.surface
    assert hasattr(ifcopenshell.api.surface, "create_terrain")

def test_ifcopenshell_api_grading_imports():
    import ifcopenshell.api.grading
    assert hasattr(ifcopenshell.api.grading, "create_grading_group")

def test_ifcopenshell_api_earthwork_imports():
    import ifcopenshell.api.earthwork
    assert hasattr(ifcopenshell.api.earthwork, "create_earthworks_cut")
