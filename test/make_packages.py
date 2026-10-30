"""Build real Mixar engine packages for the Unreal E2E with the Mixar desktop's
own exporter (``export_package(engine="unreal")``), run in a stock Blender:

    Blender --background --factory-startup --python test/make_packages.py -- \
        <client scripts dir> <out dir> [<rigged character .glb>]

Writes into <out dir>:
- ``UEQA_PropYard``: 40 props in a 8 x 5 grid, mixed roles (prop, pickup,
  door with a hinge, hazard, goal), bodies and collision shapes (box, convex,
  mesh, none) — each object keeps its own origin;
- (``UEQA_Arena`` has two ``bombsite`` empties, A and B, on the CT half, parented to its floor);
- ``UEQA_Robot``: a mesh on a custom 3-bone rig, exported (as the agent did)
  with only the mesh named — it must still import skinned;
- ``UEQA_Course``: a small winnable level (coins, a hinged door in the only
  gap of a wall, the flag behind it, a spike, a spawn and a checkpoint);
- ``UEQA_Hero``: the rigged character (a Tripo auto-rig), when given;
- ``UEQA_Rifle``: a rifle by the weapon convention (origin on the pistol
  grip, barrel toward Blender -Y, top up), ``mixar_role=weapon``;
- ``UEQA_Arena``: a small shooter map (floor, walls, cover crates, a mid
  wall with gaps) with CT and T spawn markers (``mixar_team``).

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


def course():
    """A small level a player can win: three coins on the way to a wall whose
    only gap is a hinged door; the flag behind it. A spike off the path, a
    checkpoint pad halfway. Floor 30 x 12 m; the wall runs to the floor's
    edges, so the door is the only way through."""
    from mathutils import Matrix  # noqa: PLC0415 - Blender only

    bpy.ops.wm.read_factory_settings(use_empty=True)
    names = []

    def box(name, size, at, tags, rgb, pivot_offset=(0.0, 0.0, 0.0)):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
        obj = bpy.context.object
        obj.data.transform(Matrix.Diagonal((*size, 1.0)))
        obj.data.transform(Matrix.Translation(pivot_offset))
        obj.location = at
        add(obj, name, tags, rgb)

    def add(obj, name, tags, rgb):
        obj.name = obj.data.name = name
        obj.data.materials.append(material(f"M_{name}", rgb))
        for key, value in tags.items():
            obj[key] = value
        names.append(name)

    static = {"mixar_role": "prop", "mixar_body": "static", "mixar_collision": "box"}
    box("Floor", (30.0, 12.0, 0.2), (6.0, 0.0, -0.1), static, (0.35, 0.35, 0.38))
    box("WallLeft", (0.3, 5.0, 3.0), (9.0, 3.5, 1.5), static, (0.5, 0.45, 0.4))
    box("WallRight", (0.3, 5.0, 3.0), (9.0, -3.5, 1.5), static, (0.5, 0.45, 0.4))
    # Origin on the hinge edge (y = -1), the leaf spanning the 2 m gap.
    box("Door", (0.2, 2.0, 2.5), (9.0, -1.0, 0.0),
        {"mixar_role": "door", "mixar_body": "kinematic", "mixar_collision": "box", "mixar_pivot": "hinge_z"},
        (0.45, 0.25, 0.1), pivot_offset=(0.0, 1.0, 1.25))
    box("Spawn", (0.8, 0.8, 0.05), (-6.0, 0.0, 0.025),
        {"mixar_role": "spawn", "mixar_body": "none", "mixar_collision": "none"}, (0.2, 0.4, 0.9))
    box("Checkpoint", (1.0, 1.0, 0.05), (4.0, 0.0, 0.025),
        {"mixar_role": "checkpoint", "mixar_body": "none", "mixar_collision": "none"}, (0.9, 0.9, 0.2))
    for i, (x, y) in enumerate(((-2.0, 0.0), (2.0, 2.5), (6.0, -2.5))):
        bpy.ops.mesh.primitive_cylinder_add(radius=0.3, depth=0.08, location=(x, y, 0.8),
                                            rotation=(math.radians(90), 0.0, 0.0))
        add(bpy.context.object, f"Coin_{i}", {"mixar_role": "pickup", "mixar_body": "static",
                                              "mixar_collision": "convex"}, (0.95, 0.75, 0.1))
    bpy.ops.mesh.primitive_cone_add(radius1=0.5, depth=0.8, location=(2.0, -4.5, 0.4))
    add(bpy.context.object, "Spikes", {"mixar_role": "hazard", "mixar_body": "static",
                                       "mixar_collision": "convex"}, (0.8, 0.1, 0.1))
    bpy.ops.mesh.primitive_cylinder_add(radius=0.4, depth=2.0, location=(13.0, 0.0, 1.0))
    add(bpy.context.object, "Flag", {"mixar_role": "goal", "mixar_body": "none", "mixar_collision": "none"},
        (0.1, 0.7, 0.2))
    result = export_package.export_package(names, fmt="fbx", folder="UEQA_Course", engine="unreal",
                                           bake_materials=False)
    print("PACKAGE", result.get("folder"), result.get("verification", {}).get("issues"))


def robot():
    """A rigid robot on a custom 3-bone rig (no humanoid naming), as a scripted
    rig comes out of Mixar: it must still import skinned."""
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.object.armature_add(location=(0.0, 0.0, 0.0))
    rig = bpy.context.object
    rig.name = rig.data.name = "Robot_Rig"
    bpy.ops.object.mode_set(mode="EDIT")
    bones = rig.data.edit_bones
    root = bones[0]
    root.name, root.head, root.tail = "Root", (0, 0, 0), (0, 0, 0.8)
    torso = bones.new("Torso")
    torso.head, torso.tail, torso.parent = (0, 0, 0.8), (0, 0, 1.4), root
    head = bones.new("Head")
    head.head, head.tail, head.parent = (0, 0, 1.4), (0, 0, 1.8), torso
    bpy.ops.object.mode_set(mode="OBJECT")
    parts = []
    for bone, size, z in (("Root", (0.4, 0.3, 0.8), 0.4), ("Torso", (0.6, 0.4, 0.6), 1.1),
                          ("Head", (0.35, 0.35, 0.35), 1.6)):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0, 0, z))
        part = bpy.context.object
        part.scale = size
        bpy.ops.object.transform_apply(scale=True)
        group = part.vertex_groups.new(name=bone)
        group.add(list(range(len(part.data.vertices))), 1.0, "REPLACE")
        parts.append(part)
    bpy.ops.object.select_all(action="DESELECT")
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    body = bpy.context.object
    body.name = body.data.name = "Robot_Body"
    body.data.materials.append(material("M_Robot", (0.7, 0.7, 0.75)))
    body.parent = rig
    body.modifiers.new("Armature", "ARMATURE").object = rig
    result = export_package.export_package(["Robot_Body"], fmt="fbx", folder="UEQA_Robot", engine="unreal",
                                           animations=[], bake_materials=False)
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


def rifle():
    """A rifle by the weapon convention: origin where the right hand grips,
    barrel toward Blender -Y, top up; about 0.9 m long."""
    from mathutils import Matrix  # noqa: PLC0415 - Blender only

    bpy.ops.wm.read_factory_settings(use_empty=True)
    parts = []
    for size, at, rot in (((0.055, 0.32, 0.075), (0.0, -0.07, 0.035), 0.0),     # receiver
                          ((0.05, 0.24, 0.06), (0.0, -0.34, 0.035), 0.0),       # handguard
                          ((0.045, 0.27, 0.065), (0.0, 0.22, 0.01), 0.1),       # stock
                          ((0.035, 0.045, 0.11), (0.0, 0.015, -0.05), -0.35),   # pistol grip
                          ((0.035, 0.07, 0.19), (0.0, -0.13, -0.08), 0.3)):     # magazine
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
        part = bpy.context.object
        part.data.transform(Matrix.Diagonal((*size, 1.0)))
        part.data.transform(Matrix.Rotation(rot, 4, "X"))
        part.data.transform(Matrix.Translation(at))
        parts.append(part)
    bpy.ops.mesh.primitive_cylinder_add(radius=0.012, depth=0.36, location=(0.0, -0.6, 0.045),
                                        rotation=(math.radians(90), 0.0, 0.0))
    parts.append(bpy.context.object)
    bpy.ops.object.select_all(action="DESELECT")
    for part in parts:
        part.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    gun = bpy.context.object
    gun.name = gun.data.name = "Rifle"
    gun.data.materials.append(material("M_Rifle", (0.12, 0.11, 0.1)))
    gun["mixar_role"], gun["mixar_body"], gun["mixar_collision"] = "weapon", "none", "none"
    result = export_package.export_package(["Rifle"], fmt="fbx", folder="UEQA_Rifle", engine="unreal",
                                           bake_materials=False)
    print("PACKAGE", result.get("folder"), result.get("verification", {}).get("issues"))


def arena():
    """A 40 x 24 m shooter map: walls, cover, a mid wall with three gaps, T
    spawns in the west, CT spawns in the east."""
    from mathutils import Matrix  # noqa: PLC0415 - Blender only

    bpy.ops.wm.read_factory_settings(use_empty=True)
    names = []

    def box(name, size, at, tags, rgb):
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
        obj = bpy.context.object
        obj.data.transform(Matrix.Diagonal((*size, 1.0)))
        obj.location = at
        obj.name = obj.data.name = name
        obj.data.materials.append(material(f"M_{name}", rgb))
        for key, value in tags.items():
            obj[key] = value
        names.append(name)

    static = {"mixar_role": "prop", "mixar_body": "static", "mixar_collision": "box"}
    sand, wall, crate = (0.62, 0.52, 0.38), (0.72, 0.62, 0.46), (0.45, 0.32, 0.18)
    box("Floor", (40.0, 24.0, 0.2), (0.0, 0.0, -0.1), static, sand)
    for i, (size, at) in enumerate((((40.0, 0.4, 3.5), (0.0, 12.0, 1.75)), ((40.0, 0.4, 3.5), (0.0, -12.0, 1.75)),
                                    ((0.4, 24.0, 3.5), (20.0, 0.0, 1.75)), ((0.4, 24.0, 3.5), (-20.0, 0.0, 1.75)))):
        box(f"Wall_{i}", size, at, static, wall)
    for i, (y0, y1) in enumerate(((-12.0, -7.0), (-4.5, -1.2), (1.2, 4.5), (7.0, 12.0))):
        box(f"Mid_{i}", (0.6, y1 - y0, 3.0), (0.0, (y0 + y1) / 2, 1.5), static, wall)
    for i, (x, y) in enumerate(((-8.0, 5.0), (-8.0, -6.0), (8.0, 6.0), (8.0, -5.0), (-3.0, 0.0), (3.5, 0.5))):
        box(f"Crate_{i}", (1.4, 1.4, 1.4), (x, y, 0.7), static, crate)
    for i, y in enumerate((-3.0, 0.0, 3.0)):
        box(f"SpawnT_{i}", (0.8, 0.8, 0.05), (-17.0, y, 0.025),
            {"mixar_role": "spawn", "mixar_team": "t", "mixar_body": "none", "mixar_collision": "none"},
            (0.9, 0.6, 0.2))
        box(f"SpawnCT_{i}", (0.8, 0.8, 0.05), (17.0, y, 0.025),
            {"mixar_role": "spawn", "mixar_team": "ct", "mixar_body": "none", "mixar_collision": "none"},
            (0.2, 0.4, 0.9))
    # bomb sites as EMPTIES under the floor (how an agent marks them): the manifest carries them as markers
    floor = bpy.data.objects["Floor"]
    for name, y in (("SiteA", 7.0), ("SiteB", -7.0)):
        site = bpy.data.objects.new(name, None)
        bpy.context.scene.collection.objects.link(site)
        site.location = (9.0, y, 0.0)
        site.parent = floor
        site.matrix_parent_inverse = floor.matrix_world.inverted()
        site["mixar_role"] = "bombsite"
    result = export_package.export_package(names, fmt="fbx", folder="UEQA_Arena", engine="unreal",
                                           bake_materials=False)
    print("PACKAGE", result.get("folder"), result.get("verification", {}).get("issues"))


prop_yard()
course()
robot()
rifle()
arena()
if rig:
    hero(rig)
