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

from . import (ADAPTER_VERSION, MIXAR_FOLDER, blueprints, config, frames, game_spec, level, logs, nodes,
               package, play, playtest)

# The server's name for this toolset (module path + class name); the desktop
# reads it from the discovery file.
TOOLSET = "mixar_link.toolsets.MixarLinkTools"
# The engine calls this release answers (status lists them, so the agent works
# only with these while Unreal's coverage grows toward Godot's).
TOOLS = ("status", "scene_tree", "import_package", "new_scene", "open_scene", "save_scene", "place",
         "remove_node", "add_node", "set_property", "blueprint", "play", "stop", "capture", "log", "playtest")
MAX_NODES = 2000
# Defaults Unreal's tool schema cannot carry (it gives only numbers and bools a
# default; a string, a list or None makes the argument required). The
# discovery file publishes these and the Mixar desktop fills them in for
# arguments a call leaves out.
ARG_DEFAULTS = {
    "new_scene": {"template": "", "player_position": [], "look": "", "title": "", "objective": ""},
    "place": {"name": "", "position": [0.0, 0.0, 0.0], "parent": "", "animation": ""},
    "play": {"scene": "main"},
    "capture": {"source": "game"},
    "add_node": {"parent": "", "script": "", "position": []},
    "blueprint": {"path": "", "graph": "", "code": "", "name": "", "type": "", "parent": "", "query": ""},
}
# Arguments of any JSON shape, which Unreal's tool schema cannot type: the
# desktop sends each as one JSON-encoded string (the discovery file lists them).
JSON_ARGS = {"playtest": ["steps"], "set_property": ["value"]}


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


PLAYING = ("The game is running: Unreal saves and compiles assets only in the editor. Stop it first "
           "(engine_play action=stop), then call this again.")


def _while_playing() -> str:
    """Why an asset-changing call must wait for the game to stop, else ""."""
    from . import play
    return PLAYING if play.playing() else ""


def _async(start):
    """An async tool's result; a failure while starting it is the answer, not
    a broken call."""
    try:
        return start()
    except Exception as exc:  # noqa: BLE001
        unreal.log_error(f"[Mixar Link] {exc}")
        return play.done(_err(str(exc)))


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
            if not isinstance(actor, (unreal.StaticMeshActor, unreal.SkeletalMeshActor)):
                comps = [c.get_name() for c in actor.get_components_by_class(unreal.SceneComponent)]
                if comps:  # what Component.Property can name
                    entry["components"] = comps[:12]
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
        return _err(_while_playing()) if _while_playing() else _reply(package.import_package(source_dir, folder))

    @toolset_registry.tool_call
    @staticmethod
    def new_scene(name: str, template: str, player_position: list[float], look: str, title: str, objective: str,
                  set_main: bool = True, with_defaults: bool = True, overwrite: bool = False, ground: bool = False,
                  floating: bool = False) -> str:
        """Makes the level /Game/Mixar/Levels/<name> and opens it.

        Args:
            name: Letters, digits and _.
            set_main: Make it the project's main level (owned projects only).
            with_defaults: Add a sun, sky, clouds, fog, post process and a PlayerStart.
            look: The light: day (default), sunset, dawn, night or overcast.
            floating: Islands in the sky: the ground and the cloud layer sink below the level.
            title: The template game's title card (default: the level's name).
            objective: The line under the title ("Collect the 5 sun crystals").
            overwrite: Replace an existing level of that name.
            template: A playable game around the level: third_person, top_down
                or platformer (the BP_MixarGameMode rules: pickups open doors, a
                goal wins once they are open, hazards and falls respawn; a HUD), or
                shooter (first-person CT vs T rounds with bots; team spawns are
                spawn markers tagged mixar_team, characters and the weapon come
                from placed packages).
            ground: Add a 60 m floor.
            player_position: Where the PlayerStart goes (Blender frame).

        Returns:
            JSON: {"ok", "data": {scene, main, look, replaced_main?}}.
        """
        if template and template not in game_spec.TEMPLATES:
            return _err(f"template must be one of {', '.join(game_spec.TEMPLATES)}.")
        if not name or not all(c.isalnum() or c == "_" for c in name) or len(name) > 64:
            return _err("name must be letters, digits and _ (at most 64).")
        if look and look not in level.LOOKS:
            return _err(f"look must be one of {', '.join(level.LOOKS)}.")
        if _while_playing():
            return _err(_while_playing())
        return _reply(level.new_scene(name, set_main, with_defaults, overwrite, ground,
                                      list(player_position) if player_position else None, template or "",
                                      look or "", bool(floating), title or "", objective or ""))

    @toolset_registry.tool_call
    @staticmethod
    def open_scene(scene: str) -> str:
        """Opens a level.

        Args:
            scene: The level's asset path (/Game/...).

        Returns:
            JSON: {"ok", "data": {scene}}.
        """
        return _err(_while_playing()) if _while_playing() else _reply(level.open_scene(scene))

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
    def add_node(type: str, name: str, parent: str, script: str, position: list[float]) -> str:  # noqa: A002
        """Adds an actor to the open level and saves it.

        Args:
            type: A built-in actor class (PointLight, TriggerBox, TextRenderActor,
                /Script/Engine.SpotLight …) or a Blueprint under /Game/Mixar.
            name: The actor's label.
            parent: Attach to this actor (a scene_tree path).
            script: A Blueprint path to spawn instead of ``type`` (Godot's script).
            position: Blender frame (Z up, metres).

        Returns:
            JSON: {"ok", "data": {node, type, scene}}.
        """
        at = list(position) if position else None
        if at is not None and len(at) != 3:
            return _err("position must be [x, y, z].")
        return _reply(nodes.add_node(script or type, name, parent or "", at))

    @toolset_registry.tool_call
    @staticmethod
    def set_property(node: str, property: str, value: str) -> str:  # noqa: A002
        """Sets one property of an actor (or ``Component.Property``) in the open level and saves it.

        Args:
            node: A scene_tree path or an actor label.
            property: position / yaw_deg (Blender frame), rotation ([roll, pitch, yaw]),
                scale, label, hidden, tags, or any property name (Unreal units), a
                Blueprint variable included; a name the actor lacks is looked for on
                its components (intensity, light_color …); Component.Property names one.
            value: The value, JSON-encoded.

        Returns:
            JSON: {"ok", "data": {node, property, scene}}.
        """
        return _reply(nodes.set_property(node, property, value))

    @toolset_registry.tool_call
    @staticmethod
    def blueprint(action: str, path: str, graph: str, code: str, name: str, type: str,  # noqa: A002
                  parent: str, query: str, output: bool = False) -> str:
        """Makes, reads and writes Blueprints (Epic's graph DSL); writes only under /Game/Mixar.

        Args:
            action: docs | create | read | write | add_variable | add_param |
                find_nodes | node_pins | compile.
            path: The Blueprint (/Game/Mixar/Blueprints/BP_Name).
            graph: EventGraph (default) or a function's name (write makes it).
            code: write only: (event …) / (fn …) forms; each replaces that graph part.
            name: add_variable / add_param: the name.
            type: add_variable / add_param: bool, int, float, string, name, text,
                Vector, Rotator, Transform, LinearColor, or a class path; [] = array.
            parent: create only: Actor, Character, ActorComponent, … or a class path.
            query: find_nodes: a search text; node_pins: a node type id.
            output: add_param only: an output instead of an input.

        Returns:
            JSON: {"ok", "data": {...}}.
        """
        if action not in ("docs", "read", "find_nodes", "node_pins") and _while_playing():
            return _err(_while_playing())
        return _reply(blueprints.blueprint(action, path, graph, code, name, type, parent, query, bool(output)))

    @toolset_registry.tool_call
    @staticmethod
    def playtest(steps: str) -> unreal.ToolCallAsyncResultString:
        """Plays the running game with scripted steps and reports the game state after each.

        Args:
            steps: JSON list of steps: {hold, seconds} | {press} | {wait} |
                {walk_to: [x, y, z] Blender frame, timeout} | {prove_loop: true, timeout}
                | {inspect: {node, properties}} | {state: true}; shooter: {fire: seconds}
                | {reload: true} | {aim_at: [x, y, z]} | {god: bool} (the player takes no damage).

        Returns:
            JSON: {"ok", "data": {steps, final_state}}.
        """
        return _async(lambda: playtest.run(steps))

    @toolset_registry.tool_call
    @staticmethod
    def play(scene: str) -> unreal.ToolCallAsyncResultString:
        """Runs the game in the editor (Play In Editor) and waits until its player exists.

        Args:
            scene: main | current | a level's asset path.

        Returns:
            JSON: {"ok", "data": {playing, game_connected, scene, log_seq}}.
        """
        return _async(lambda: play.play(scene or "main"))

    @toolset_registry.tool_call
    @staticmethod
    def stop() -> unreal.ToolCallAsyncResultString:
        """Stops the running game.

        Returns:
            JSON: {"ok", "data": {playing}}.
        """
        return _async(lambda: play.stop())

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
        return _async(lambda: play.capture(source if source in ("game", "editor") else "game", max_width))

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
