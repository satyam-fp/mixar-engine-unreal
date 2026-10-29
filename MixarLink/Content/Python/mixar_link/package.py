"""Mixar packages into the project: ``import_package``.

A package for Unreal (``export_asset(engine="unreal")``) is an FBX plus
``manifest.json``. Each object keeps its own origin (rotation and scale are
baked; the manifest records the origin in Blender's frame), its ``UCX_``
convex hulls ride in the same FBX, and its ``mixar_*`` tags and collision
choice are in ``manifest.engine.objects``. A rigged humanoid also carries a
bone map onto the UE5 Mannequin (``engine.skeletons``).

The FBX is imported into ``/Game/Mixar/<folder>`` with each object as its own
StaticMesh in local space, so its pivot stays at its origin (a door turns
about its hinge); a rigged package imports as a SkeletalMesh with its clips.
Every mesh asset is tagged (asset metadata ``mixar_package``,
``mixar_object``, ``mixar_origin`` and the ``mixar_*`` tags): ``place`` reads
them to put the package together in a level. A mesh-collision object is set
to use its render mesh as collision (complex as simple).
"""

import json
import os
import re

import unreal

from . import MIXAR_FOLDER, retarget

SAFE_NAME = re.compile(r"^[A-Za-z0-9 ._-]{1,96}$")
TAG_KEYS = ("role", "body", "nav", "pivot", "light")


def safe_folder(folder: str) -> str:
    """The content-browser folder name for a package folder name."""
    name = re.sub(r"[^A-Za-z0-9_]", "_", folder.strip()).strip("_")
    return name or "Package"


def _main_file(manifest: dict, source_dir: str) -> str:
    for entry in manifest.get("files") or []:
        name = entry.get("file") if isinstance(entry, dict) else str(entry)
        if name and name.lower().endswith(".fbx") and "/" not in name:
            return os.path.join(source_dir, name)
    return ""


def _fbx_options(skeletal: bool):
    options = unreal.FbxImportUI()
    options.automated_import_should_detect_type = False
    options.import_mesh = True
    options.import_as_skeletal = skeletal
    kind = unreal.FBXImportType.FBXIT_SKELETAL_MESH if skeletal else unreal.FBXImportType.FBXIT_STATIC_MESH
    options.mesh_type_to_import = kind
    options.original_import_type = kind
    options.import_materials = True
    options.import_textures = True
    options.import_animations = skeletal
    if skeletal:
        options.create_physics_asset = False
    else:
        data = options.static_mesh_import_data
        data.combine_meshes = False
        # Local space: each mesh's pivot is its object's origin.
        data.set_editor_property("transform_vertex_to_absolute", False)
        data.set_editor_property("bake_pivot_in_vertex", False)
        data.auto_generate_collision = False
    return options


def _import(source: str, dest: str, skeletal: bool) -> list:
    task = unreal.AssetImportTask()
    task.filename = source
    task.destination_path = dest
    task.destination_name = ""
    task.replace_existing = True
    task.automated = True
    task.save = False
    task.factory = unreal.FbxFactory()
    task.options = _fbx_options(skeletal)
    unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks([task])
    return [str(p).split(".", 1)[0] for p in task.get_editor_property("imported_object_paths")]


def _asset_for(obj_name: str, assets: dict):
    """The imported mesh for a manifest object: named after it, or
    ``<file stem>_<object>`` when the FBX held several meshes."""
    if obj_name in assets:
        return assets[obj_name]
    safe = safe_folder(obj_name)
    for name, asset in assets.items():
        if name == safe or name.endswith("_" + obj_name) or name.endswith("_" + safe):
            return asset
    return None


def _tag(asset, values: dict) -> None:
    for key, value in values.items():
        unreal.EditorAssetLibrary.set_metadata_tag(asset, key, str(value))


def _origin(entry: dict) -> str:
    origin = entry.get("origin") or [0.0, 0.0, 0.0]
    return ",".join(f"{float(v):.4f}" for v in origin[:3])


def import_package(source_dir: str, folder: str) -> dict:
    """Import the package at ``source_dir`` as ``/Game/Mixar/<folder>``."""
    if not SAFE_NAME.match(folder or ""):
        return {"error": "folder must be a plain name (letters, digits, . _ - and spaces)."}
    try:
        with open(os.path.join(source_dir, "manifest.json"), encoding="utf-8") as fh:
            manifest = json.load(fh)
    except (OSError, ValueError):
        return {"error": "The folder has no readable manifest.json; it is not a Mixar package."}
    engine = manifest.get("engine") if isinstance(manifest.get("engine"), dict) else {}
    if engine.get("target") not in ("unreal", "uefn"):
        return {"error": "This package was not exported for Unreal; export it again with "
                         "export_asset(engine=\"unreal\") so collision and tags come along."}
    source = _main_file(manifest, source_dir)
    if not source or not os.path.isfile(source):
        return {"error": "The manifest names no FBX file in the package."}
    name = safe_folder(folder)
    dest = f"{MIXAR_FOLDER}/{name}"
    skeletons = [s for s in engine.get("skeletons") or [] if isinstance(s, dict)]
    skeletal = bool(skeletons)
    paths = _import(source, dest, skeletal)
    if not paths:
        return {"error": "Unreal imported nothing from the package's FBX; read log for the importer's reason."}
    loaded = {p.rsplit("/", 1)[-1]: unreal.EditorAssetLibrary.load_asset(p) for p in paths}
    kind = unreal.SkeletalMesh if skeletal else unreal.StaticMesh
    meshes = {n: a for n, a in loaded.items() if isinstance(a, kind)}
    objects, missing, hulls, complex_simple = [], [], 0, 0
    entries = [e for e in engine.get("objects") or [] if isinstance(e, dict) and e.get("name")]
    for entry in entries:
        asset = next(iter(meshes.values())) if skeletal and len(meshes) == 1 else _asset_for(entry["name"], meshes)
        if asset is None:
            missing.append(entry["name"])
            continue
        collision = entry.get("collision") or {}
        tags = {"mixar_package": name, "mixar_object": entry["name"], "mixar_origin": _origin(entry),
                "mixar_collision": collision.get("shape") or "none"}
        tags.update({f"mixar_{k}": entry[k] for k in TAG_KEYS if entry.get(k)})
        _tag(asset, tags)
        if isinstance(asset, unreal.StaticMesh):
            body = asset.get_editor_property("body_setup")
            if collision.get("complex_as_simple") and body:
                body.set_editor_property("collision_trace_flag", unreal.CollisionTraceFlag.CTF_USE_COMPLEX_AS_SIMPLE)
                complex_simple += 1
            if body:
                hulls += len(body.get_editor_property("agg_geom").get_editor_property("convex_elems"))
        objects.append(entry["name"])
        if skeletal:
            break  # one character per rigged package
    out = {"folder": name, "main_scene": dest, "objects": objects, "meshes": len(meshes),
           "collision": {"convex_hulls": hulls, "complex_as_simple": complex_simple},
           "issues": list(engine.get("issues") or [])}
    if missing:
        out["missing"] = missing
    anims = [p for p in paths if isinstance(loaded.get(p.rsplit("/", 1)[-1]), unreal.AnimSequence)]
    if anims:
        out["animations"] = anims
    if skeletal and meshes:
        character = next(iter(meshes.values()))
        skeleton = skeletons[0]
        _tag(character, {"mixar_bone_naming": skeleton.get("naming") or "",
                         "mixar_bone_map": json.dumps(skeleton.get("bones") or {})})
        setup = retarget.prepare(character, skeleton.get("bones") or {}, dest, name)
        out["retarget"] = setup
        if "error" not in setup:
            out["mannequin_clips"] = retarget.mannequin_clips()
    unreal.EditorAssetLibrary.save_directory(dest)
    return out
