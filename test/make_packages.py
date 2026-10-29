"""Build real Mixar engine packages for the Unreal E2E with the Mixar desktop's
own exporter (``export_package(engine="unreal")``), run in a stock Blender:

    Blender --background --factory-startup --python test/make_packages.py -- \
        <client scripts dir> <out dir> [<rigged character .glb>]

Writes into <out dir>:
- ``UEQA_PropYard``: 40 props in a 8 x 5 grid, mixed roles (prop, pickup,
  door with a hinge, hazard, goal), bodies and collision shapes (box, convex,
  mesh, none) — each object keeps its own origin;
- ``UEQA_Hero``: the rigged character (a Tripo auto-rig), when given.

The exporter is loaded straight from the client's ``space_mixie_chat/core``
folder as a standalone package, so nothing else of the app is needed.
"""

import importlib
import math
import os
import sys
import types

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
scripts, out = args[0], os.path.abspath(args[1])
rig = args[2] if len(args) > 2 else ""

# Paint stacks and telemetry are app-only; these meshes have neither.
for name in ("mixar", "mixar.modules", "mixar.modules.paint", "mixar.modules.paint.core",
             "mixar.modules.paint.core.asset_export", "mixar.modules.paint.core.asset_export.bake_and_assign"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["mixar.modules.paint.core.asset_export.bake_and_assign"].create_export_material = lambda *a: None

core = os.path.join(scripts, "mixar", "modules", "space_mixie_chat", "core")
pkg = types.ModuleType("mx_core")
pkg.__path__ = [core]
sys.modules["mx_core"] = pkg
export_package = importlib.import_module("mx_core.export_package")


def destination(where, subfolder=None, create=True):
    path = os.path.join(out, subfolder) if subfolder else out
    if create:
        os.makedirs(path, exist_ok=True)
    return path


export_package.destination = destination  # the test's folder, not the user's exports


def material(name, rgb):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    mat.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*rgb, 1.0)
    return mat


def prop_yard():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    kinds = [
        ("Crate", "cube", {"mixar_role": "prop", "mixar_body": "static", "mixar_collision": "box"}, (0.6, 0.4, 0.2)),
        ("Coin", "cylinder", {"mixar_role": "pickup", "mixar_body": "static", "mixar_collision": "convex"},
         (0.9, 0.75, 0.1)),
        ("Rock", "ico", {"mixar_role": "prop", "mixar_body": "static", "mixar_collision": "mesh"}, (0.4, 0.4, 0.42)),
        ("Door", "cube", {"mixar_role": "door", "mixar_body": "kinematic", "mixar_collision": "box",
                          "mixar_pivot": "hinge_z"}, (0.3, 0.2, 0.1)),
        ("Spikes", "cone", {"mixar_role": "hazard", "mixar_body": "static", "mixar_collision": "convex"},
         (0.7, 0.1, 0.1)),
        ("Flag", "cylinder", {"mixar_role": "goal", "mixar_body": "none", "mixar_collision": "none"},
         (0.1, 0.6, 0.2)),
        ("Barrel", "cylinder", {"mixar_role": "prop", "mixar_body": "rigid", "mixar_collision": "convex"},
         (0.2, 0.3, 0.6)),
        ("Grass", "cube", {"mixar_role": "prop", "mixar_body": "none", "mixar_collision": "none",
                           "mixar_nav": "ignore"}, (0.2, 0.7, 0.2)),
    ]
    mats = {k[0]: material(f"M_{k[0]}", k[3]) for k in kinds}
    names = []
    for i in range(40):
        kind, shape, tags, _ = kinds[i % len(kinds)]
        x, y = (i % 8) * 2.0 - 7.0, (i // 8) * 2.0 - 4.0
        if shape == "cube":
            bpy.ops.mesh.primitive_cube_add(size=0.8 if kind != "Door" else 1.0, location=(x, y, 0.4))
            if kind == "Door":
                bpy.context.object.scale = (1.0, 0.1, 2.0)
        elif shape == "cylinder":
            bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=0.6, location=(x, y, 0.3))
        elif shape == "cone":
            bpy.ops.mesh.primitive_cone_add(radius1=0.4, depth=0.8, location=(x, y, 0.4))
        else:
            bpy.ops.mesh.primitive_ico_sphere_add(radius=0.4, subdivisions=2, location=(x, y, 0.4))
        obj = bpy.context.object
        obj.name = obj.data.name = f"{kind}_{i:02d}"
        obj.rotation_euler.z = math.radians(15 * (i % 6))
        obj.data.materials.append(mats[kind])
        for key, value in tags.items():
            obj[key] = value
        names.append(obj.name)
    result = export_package.export_package(names, fmt="fbx", folder="UEQA_PropYard", engine="unreal",
                                           bake_materials=False)
    print("PACKAGE", result.get("folder"), result.get("verification", {}).get("issues"))


def hero(glb):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb)
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    arm.name = "Hero"
    meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.find_armature() == arm]
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
        bpy.data.objects.remove(o)
    for m in meshes:
        m["mixar_role"] = "player"
    result = export_package.export_package([arm.name] + [m.name for m in meshes], fmt="fbx", folder="UEQA_Hero",
                                           engine="unreal", animations=[], bake_materials=False)
    print("PACKAGE", result.get("folder"), result.get("verification", {}).get("issues"))


prop_yard()
if rig:
    hero(rig)
