"""Mixar Link's toolset, registered with Unreal's MCP server beside Epic's.

The tools share the Godot add-on's names and result shapes (``status``,
``scene_tree``, ``place`` …), so the Mixar agent drives either engine with
the same calls. Each tool returns a JSON string, ``{"ok": true, "data":
{...}}`` or ``{"ok": false, "error": "..."}``: the server hands a Python return
value back as ``{"returnValue": ...}`` and only flat string maps survive its
type mapping, while scene trees nest. Tools that wait on the editor (play,
stop, capture) return the same string asynchronously. Positions are
Blender's frame (``frames``).

Only purpose-built tools live here; nothing runs arbitrary code.
"""

import json

import unreal

import toolset_registry
from toolset_registry.registration import Registration

from . import ADAPTER_VERSION, MIXAR_FOLDER, config, frames, level, logs, package, play

# The server's name for this toolset (module path + class name); the desktop
# reads it from the discovery file.
TOOLSET = "mixar_link.toolsets.MixarLinkTools"
# The engine calls this release answers (status lists them, so the agent works
# only with these while Unreal's coverage grows toward Godot's).
TOOLS = ("status", "scene_tree", "import_package", "new_scene", "open_scene", "save_scene", "place",
         "remove_node", "play", "stop", "capture", "log")
MAX_NODES = 2000
# Defaults Unreal's tool schema cannot carry (it gives only numbers and bools a
# default; a string, a list or None makes the argument required). The
# discovery file publishes these and the Mixar desktop fills them in for
# arguments a call leaves out.
ARG_DEFAULTS = {
    "new_scene": {"template": "", "player_position": []},
    "place": {"name": "", "position": [0.0, 0.0, 0.0], "parent": "", "animation": ""},
    "play": {"scene": "main"},
    "capture": {"source": "game"},
}


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, "data": data})


def _err(message: str, **detail) -> str:
    return json.dumps({"ok": False, "error": message, **({"data": detail} if detail else {})})


def _reply(out: dict) -> str:
    """A module's result dict as the tool's answer (``error`` = failure)."""
    if "error" in out:
        return _err(out["error"], **(out.get("data") or {}))
    return _ok(out)


def _sub(cls):
    return unreal.get_editor_subsystem(cls)


def _package(obj) -> str:
    """'/Game/Maps/Level' for an object path '/Game/Maps/Level.Level'."""
    return obj.get_path_name().split(".", 1)[0] if obj else ""


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
    """Mixar Link: the Mixar agent's tools (import packages, build levels,
    play, see, read the log), shared with Mixar Link for Godot. Results are
    JSON strings; positions are Blender's frame (Z up, metres)."""

    @toolset_registry.tool_call
    @staticmethod
    def status() -> str:
        """Engine, project, the open level, the main level and whether the game runs.

        Returns:
            JSON: {"ok", "data": {engine, version, project_name, edited_scene,
            main_scene, playing, adapter_version, mixar_folder, project_mode,
            log_seq, tools}}.
        """
        return _ok({
            "engine": "unreal",
            "version": unreal.SystemLibrary.get_engine_version(),
            "project_name": unreal.SystemLibrary.get_game_name(),
            "edited_scene": level.level_path(),
            "main_scene": level.main_level(),
            "playing": play.playing(),
            "adapter_version": ADAPTER_VERSION,
            "mixar_folder": MIXAR_FOLDER,
            "project_mode": config.mode(),
            "log_seq": logs.latest(),
            "tools": list(TOOLS),
        })

    @toolset_registry.tool_call
    @staticmethod
    def scene_tree(max_nodes: int = 200) -> str:
        """The open level's actors: outliner path, class, Blender-frame position,
        yaw, ``instance_of`` (the mesh or Blueprint asset), tags and attachments.

        Args:
            max_nodes: At most this many actors (1-2000).

        Returns:
            JSON: {"ok", "data": {scene, nodes, total, truncated}}.
        """
        world = level.world()
        if world is None:
            return _err("No level is open.")
        limit = max(1, min(int(max_nodes or 200), MAX_NODES))
        actors = _sub(unreal.EditorActorSubsystem).get_all_level_actors()
        nodes = []
        for actor in actors[:limit]:
            entry = {
                "path": level._outliner_path(actor),
                "type": actor.get_class().get_name(),
                "position": frames.to_blender(actor.get_actor_location()),
                "yaw_deg": frames.yaw_to_blender(actor.get_actor_rotation().yaw),
                "children": len(actor.get_attached_actors() or []),
            }
            parent = actor.get_attach_parent_actor()
            if parent:
                entry["parent"] = level._outliner_path(parent)
            source = _instance_of(actor)
            if source:
                entry["instance_of"] = source
            tags = [str(t) for t in actor.tags if str(t).startswith("mixar_")]
            if tags:
                entry["tags"] = tags
            nodes.append(entry)
        return _ok({"scene": _package(world), "nodes": nodes, "total": len(actors),
                    "truncated": len(actors) > len(nodes)})

    @toolset_registry.tool_call
    @staticmethod
    def import_package(source_dir: str, folder: str) -> str:
        """Imports a Mixar package (an export_asset(engine="unreal") folder) into
        /Game/Mixar/<folder>: one StaticMesh per object with its collision and
        tags, or a SkeletalMesh with its clips and a Mannequin retargeter.

        Args:
            source_dir: The package folder on this machine.
            folder: The package's name (letters, digits, . _ - and spaces).

        Returns:
            JSON: {"ok", "data": {folder, main_scene, objects, meshes, collision,
            issues, animations?, retarget?, mannequin_clips?}}.
        """
        return _reply(package.import_package(source_dir, folder))

    @toolset_registry.tool_call
    @staticmethod
    def new_scene(name: str, template: str, player_position: list[float], set_main: bool = True,
                  with_defaults: bool = True, overwrite: bool = False, ground: bool = False) -> str:
        """Makes the level /Game/Mixar/Levels/<name> and opens it.

        Args:
            name: Letters, digits and _.
            set_main: Make it the project's main level (owned projects only).
            with_defaults: Add a sun, sky, fog and a PlayerStart.
            overwrite: Replace an existing level of that name.
            template: Not available in Unreal yet; leave empty.
            ground: Add a 60 m floor.
            player_position: Where the PlayerStart goes (Blender frame).

        Returns:
            JSON: {"ok", "data": {scene, main}}.
        """
        if template:
            return _err("Game templates are not in Mixar Link for Unreal yet; make the level without one.")
        if not name or not all(c.isalnum() or c == "_" for c in name) or len(name) > 64:
            return _err("name must be letters, digits and _ (at most 64).")
        return _reply(level.new_scene(name, set_main, with_defaults, overwrite, ground,
                                      list(player_position) if player_position else None))

    @toolset_registry.tool_call
    @staticmethod
    def open_scene(scene: str) -> str:
        """Opens a level.

        Args:
            scene: The level's asset path (/Game/...).

        Returns:
            JSON: {"ok", "data": {scene}}.
        """
        return _reply(level.open_scene(scene))

    @toolset_registry.tool_call
    @staticmethod
    def save_scene() -> str:
        """Saves the open level.

        Returns:
            JSON: {"ok", "data": {saved}}.
        """
        reason = level.refusal()
        return _err(reason) if reason else _ok({"saved": level.save(), "scene": level.level_path()})

    @toolset_registry.tool_call
    @staticmethod
    def place(scene: str, name: str, position: list[float], parent: str, animation: str,
              yaw_deg: float = 0.0) -> str:
        """Puts an imported package into the open level and saves it.

        Args:
            scene: The package (import_package's main_scene).
            name: The instance's name (default: the package's).
            position: Where the package's origin goes, Blender frame (Z up, metres).
            yaw_deg: Turn about the up axis.
            parent: Attach to this actor (a scene_tree path).
            animation: A character only: an animation to loop; a Mannequin
                clip is retargeted onto the character first.

        Returns:
            JSON: {"ok", "data": {node, actors, position, scene, animation?}}.
        """
        at = list(position) if position else [0.0, 0.0, 0.0]
        if len(at) != 3:
            return _err("position must be [x, y, z].")
        return _reply(level.place(scene, name or "", at, float(yaw_deg), parent or "", animation or ""))

    @toolset_registry.tool_call
    @staticmethod
    def remove_node(node: str) -> str:
        """Removes an actor, or a placed package (its folder), from the open level.

        Args:
            node: A scene_tree path.

        Returns:
            JSON: {"ok", "data": {removed, scene}}.
        """
        return _reply(level.remove_node(node))

    @toolset_registry.tool_call
    @staticmethod
    def play(scene: str) -> unreal.ToolCallAsyncResultString:
        """Runs the game in the editor (Play In Editor) and waits until its player exists.

        Args:
            scene: main | current | a level's asset path.

        Returns:
            JSON: {"ok", "data": {playing, game_connected, scene, log_seq}}.
        """
        return play.play(scene or "main")

    @toolset_registry.tool_call
    @staticmethod
    def stop() -> unreal.ToolCallAsyncResultString:
        """Stops the running game.

        Returns:
            JSON: {"ok", "data": {playing}}.
        """
        return play.stop()

    @toolset_registry.tool_call
    @staticmethod
    def capture(source: str, max_width: int = 1280) -> unreal.ToolCallAsyncResultString:
        """A frame of the running game (source game) or the level editor's viewport.

        Args:
            source: game | editor.
            max_width: The frame's width in pixels (256-1920).

        Returns:
            JSON: {"ok", "data": {source, width, height, image_base64, image_mime}}.
        """
        return play.capture(source if source in ("game", "editor") else "game", max_width)

    @toolset_registry.tool_call
    @staticmethod
    def log(since: int = 0, max_lines: int = 200, errors_only: bool = False) -> str:
        """Editor and game log lines written after ``since`` (a log_seq).

        Args:
            since: The log_seq from status, play or a previous log's next.
            max_lines: At most this many lines (1-1000).
            errors_only: Only errors and warnings.

        Returns:
            JSON: {"ok", "data": {lines: [{seq, level, text}], next, more, dropped}}.
        """
        return _ok(logs.since(int(since), max(1, min(int(max_lines), 1000)), bool(errors_only)))


registration = Registration([MixarLinkTools])
