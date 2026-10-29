"""Mixar Link's toolset, registered with Unreal's MCP server beside Epic's.

The tools share the Godot add-on's names and result shapes (``status``,
``scene_tree``, …), so the Mixar agent drives either engine with the same
calls. Each tool returns a JSON string, ``{"ok": true, "data": {...}}`` or
``{"ok": false, "error": "..."}``: the server hands a Python return value back
as ``{"returnValue": ...}`` and only flat string maps survive its type
mapping, while scene trees nest. Positions are Blender's frame (``frames``).

Only purpose-built tools live here; nothing runs arbitrary code.
"""

import json

import unreal

import toolset_registry
from toolset_registry.registration import Registration

from . import ADAPTER_VERSION, MIXAR_FOLDER, frames

# The server's name for this toolset (module path + class name); the desktop
# reads it from the discovery file.
TOOLSET = "mixar_link.toolsets.MixarLinkTools"
MAX_NODES = 2000


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, "data": data})


def _err(message: str, **detail) -> str:
    return json.dumps({"ok": False, "error": message, **({"data": detail} if detail else {})})


def _sub(cls):
    return unreal.get_editor_subsystem(cls)


def _package(obj) -> str:
    """'/Game/Maps/Level' for an object path '/Game/Maps/Level.Level'."""
    return obj.get_path_name().split(".", 1)[0] if obj else ""


def _soft_path(value) -> str:
    text = str(value.export_text()) if hasattr(value, "export_text") else str(value or "")
    return text.split(".", 1)[0] if text not in ("None", "") else ""


def _main_level() -> str:
    try:
        settings = unreal.get_default_object(unreal.GameMapsSettings)
        return _soft_path(settings.get_editor_property("game_default_map"))
    except Exception:  # noqa: BLE001
        return ""


def _world():
    return _sub(unreal.UnrealEditorSubsystem).get_editor_world()


def _playing() -> bool:
    return bool(_sub(unreal.LevelEditorSubsystem).is_in_play_in_editor())


def _actor_path(actor) -> str:
    folder = str(actor.get_folder_path() or "")
    label = actor.get_actor_label()
    return f"{folder}/{label}" if folder and folder != "None" else label


def _instance_of(actor) -> str:
    if isinstance(actor, unreal.StaticMeshActor):
        mesh = actor.static_mesh_component.static_mesh
        return _package(mesh)
    if isinstance(actor, unreal.SkeletalMeshActor):
        mesh = actor.skeletal_mesh_component.get_skeletal_mesh_asset()
        return _package(mesh)
    cls = actor.get_class()
    path = cls.get_path_name() if cls else ""
    return path.split(".", 1)[0] if path.startswith("/Game/") else ""


@unreal.uclass()
class MixarLinkTools(unreal.ToolsetDefinition):
    """Mixar Link: the Mixar agent's tools (status, scene tree, …), shared with
    Mixar Link for Godot. Results are JSON strings; positions are Blender's
    frame (Z up, metres)."""

    @toolset_registry.tool_call
    @staticmethod
    def status() -> str:
        """Engine, project, the open level, the main level and whether the game runs.

        Returns:
            JSON: {"ok", "data": {engine, version, project_name, edited_scene,
            main_scene, playing, adapter_version, mixar_folder}}.
        """
        world = _world()
        return _ok({
            "engine": "unreal",
            "version": unreal.SystemLibrary.get_engine_version(),
            "project_name": unreal.SystemLibrary.get_game_name(),
            "edited_scene": _package(world),
            "main_scene": _main_level(),
            "playing": _playing(),
            "adapter_version": ADAPTER_VERSION,
            "mixar_folder": MIXAR_FOLDER,
        })

    @toolset_registry.tool_call
    @staticmethod
    def scene_tree(max_nodes: int = 200) -> str:
        """The open level's actors: outliner path, class, Blender-frame position,
        yaw, ``instance_of`` (the mesh or Blueprint asset) and attachments.

        Args:
            max_nodes: At most this many actors (1-2000).

        Returns:
            JSON: {"ok", "data": {scene, nodes, total, truncated}}.
        """
        world = _world()
        if world is None:
            return _err("No level is open.")
        limit = max(1, min(int(max_nodes or 200), MAX_NODES))
        actors = _sub(unreal.EditorActorSubsystem).get_all_level_actors()
        nodes = []
        for actor in actors[:limit]:
            entry = {
                "path": _actor_path(actor),
                "type": actor.get_class().get_name(),
                "position": frames.to_blender(actor.get_actor_location()),
                "yaw_deg": frames.yaw_to_blender(actor.get_actor_rotation().yaw),
                "children": len(actor.get_attached_actors() or []),
            }
            parent = actor.get_attach_parent_actor()
            if parent:
                entry["parent"] = _actor_path(parent)
            source = _instance_of(actor)
            if source:
                entry["instance_of"] = source
            nodes.append(entry)
        return _ok({"scene": _package(world), "nodes": nodes, "total": len(actors),
                    "truncated": len(actors) > len(nodes)})


registration = Registration([MixarLinkTools])
