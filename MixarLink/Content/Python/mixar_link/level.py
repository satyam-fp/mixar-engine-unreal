"""Levels: make, open and save them, and put packages into them.

Levels Mixar makes live under ``/Game/Mixar/Levels``. In ``plugin`` mode
(``config.mode()``) Mixar edits only levels under ``/Game/Mixar`` and never
the project's settings; in ``owned`` mode (a game Mixar made) it edits any.

``place`` puts a package together: one actor per object at its origin, moved
by ``position`` and turned by ``yaw_deg`` about the package's own origin,
under the outliner folder ``Mixar/<instance>``. Actors carry the objects'
tags as actor tags (``mixar_role=pickup`` …), take their mobility and
physics from ``mixar_body``, and a rigged character can play a Mannequin clip
(retargeted on first use).
"""

import math
import os
import re

import unreal

from . import MIXAR_FOLDER, config, frames, game, retarget

LEVELS = f"{MIXAR_FOLDER}/Levels"
INSTANCE_FOLDER = "Mixar"
MAPS_SECTION = "[/Script/EngineSettings.GameMapsSettings]"
GROUND_SIZE_M = 60.0
NAV_LABEL = "MixarNavigation"
# Roles the template game moves at run time, so their actors are Movable.
MOVING_ROLES = {"pickup", "door", "hazard", "enemy"}
# Roles the player walks through: they never block navigation.
WALKED_ROLES = {"pickup", "goal", "checkpoint", "trigger", "spawn"}


def _sub(cls):
    return unreal.get_editor_subsystem(cls)


def world():
    return _sub(unreal.UnrealEditorSubsystem).get_editor_world()


def level_path() -> str:
    w = world()
    if w is None:  # during Play In Editor the editor world reads as None; its level still knows
        current = _sub(unreal.LevelEditorSubsystem).get_current_level()
        w = current.get_outer() if current else None
    if w is None:  # or only the game's copy of it does: /Game/Levels/UEDPIE_0_Name
        game = _sub(unreal.UnrealEditorSubsystem).get_game_world()
        if game is not None:
            folder, name = game.get_path_name().split(".", 1)[0].rsplit("/", 1)
            return f"{folder}/{re.sub(r'^UEDPIE_[0-9]+_', '', name)}"
    return w.get_path_name().split(".", 1)[0] if w else ""


def main_level() -> str:
    value = config.read_layered("Engine", MAPS_SECTION, "GameDefaultMap")
    return value.split(".", 1)[0] if value else ""


def refusal() -> str:
    """Why Mixar may not edit the open level, else ""."""
    path = level_path()
    if not path:
        return "No level is open; call new_scene or open_scene first."
    if path.startswith("/Temp/"):
        return "The open level was never saved; open a level under /Game, or make one with new_scene."
    if config.mode() == "owned" or path.startswith(MIXAR_FOLDER + "/"):
        return ""
    return (f"This is the user's own project (plugin mode): Mixar edits only levels under {MIXAR_FOLDER}/, "
            f"and {path} is not one. Make a level of Mixar's own with new_scene.")


def _dirty_levels() -> list:
    return [str(p.get_name()) for p in unreal.EditorLoadingAndSavingUtils.get_dirty_map_packages()]


def _leave_level() -> str:
    """Save the open level when Mixar may, before another one opens; the
    user's unsaved level is never saved or dropped. Returns a refusal."""
    if not _dirty_levels():
        return ""
    if refusal():
        return ("The open level has unsaved changes that are the user's; ask them to save it before "
                "Mixar opens another level.")
    _sub(unreal.LevelEditorSubsystem).save_current_level()
    return ""


def save() -> bool:
    return bool(_sub(unreal.LevelEditorSubsystem).save_current_level())


def set_main(path: str) -> str:
    if config.mode() != "owned":
        return "plugin mode: the project's main level is left to the user"
    value = f"{path}.{path.rsplit('/', 1)[-1]}"
    for key in ("GameDefaultMap", "EditorStartupMap"):
        config.write(os.path.join(config.project_dir(), "Config", "DefaultEngine.ini"), MAPS_SECTION, {key: value})
    try:
        settings = unreal.get_default_object(unreal.GameMapsSettings)
        settings.set_editor_property("game_default_map", unreal.SoftObjectPath(value))
        settings.set_editor_property("editor_startup_map", unreal.SoftObjectPath(value))
    except Exception:  # noqa: BLE001 - the ini is what the next start reads
        pass
    return ""


def _spawn(cls, location=(0.0, 0.0, 0.0), pitch=0.0, yaw=0.0, label=""):
    actor = _sub(unreal.EditorActorSubsystem).spawn_actor_from_class(
        cls, unreal.Vector(*location), unreal.Rotator(roll=0.0, pitch=pitch, yaw=yaw))
    if actor and label:
        actor.set_actor_label(label)
    return actor


def _defaults(ground: bool, player_position) -> None:
    sun = _spawn(unreal.DirectionalLight, (0, 0, 1000), pitch=-45.0, yaw=-30.0, label="Sun")
    sun.light_component.set_editor_property("atmosphere_sun_light", True)
    _spawn(unreal.SkyAtmosphere, label="SkyAtmosphere")
    sky = _spawn(unreal.SkyLight, (0, 0, 500), label="SkyLight")
    sky.light_component.set_editor_property("real_time_capture", True)
    sky.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    _spawn(unreal.ExponentialHeightFog, label="Fog")
    start = frames.from_blender(player_position) if player_position else (0.0, 0.0, 100.0)
    _spawn(unreal.PlayerStart, start, label="PlayerStart")
    if ground:
        floor = _spawn(unreal.StaticMeshActor, (0, 0, -5), label="Ground")
        floor.static_mesh_component.set_static_mesh(unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube"))
        floor.set_actor_scale3d(unreal.Vector(GROUND_SIZE_M, GROUND_SIZE_M, 0.1))


def new_scene(name: str, set_as_main: bool, with_defaults: bool, overwrite: bool, ground: bool,
              player_position, template: str = "") -> dict:
    path = f"{LEVELS}/{name}"
    game_mode = None
    if template:
        classes = game.ensure()
        if "error" in classes:
            return classes
        game_mode = classes.get(template)
        if game_mode is None:
            return {"error": f"No template {template!r}; use one of {', '.join(sorted(classes))}."}
    exists = unreal.EditorAssetLibrary.does_asset_exist(path)
    if exists and not overwrite:
        return {"error": f"{path} exists; open it with open_scene, or pass overwrite."}
    if exists:  # replaced in place: opened and emptied (a level asset cannot be remade at once)
        if level_path() != path:
            opened = open_scene(path)
            if "error" in opened:
                return opened
        actors = [a for a in _sub(unreal.EditorActorSubsystem).get_all_level_actors()
                  if not isinstance(a, (unreal.WorldSettings, unreal.WorldDataLayers))]
        _sub(unreal.EditorActorSubsystem).destroy_actors(actors)
    else:
        reason = _leave_level()
        if reason:
            return {"error": reason}
        if not _sub(unreal.LevelEditorSubsystem).new_level(path):
            return {"error": f"Unreal could not make the level {path}."}
    if with_defaults:
        _defaults(ground, player_position)
    elif ground:
        _defaults(True, player_position)
    if game_mode is not None:
        _make_game(game_mode, player_position)
    save()
    out = {"scene": path, "main": False}
    if template:
        out["template"] = template
        out["game_mode"] = game_mode.get_path_name().split(".", 1)[0]
    if set_as_main:
        note = set_main(path)
        out["main"] = not note
        if note:
            out["note"] = note
    return out


def _make_game(game_mode, player_position) -> None:
    """The level runs ``game_mode`` (World Settings override), has a
    PlayerStart and a navigation volume playtests route by."""
    world().get_world_settings().set_editor_property("default_game_mode", game_mode)
    actors = _sub(unreal.EditorActorSubsystem).get_all_level_actors()
    if not any(isinstance(a, unreal.PlayerStart) for a in actors):
        start = frames.from_blender(player_position) if player_position else (0.0, 0.0, 100.0)
        _spawn(unreal.PlayerStart, start, label="PlayerStart")
    if not any(a.get_actor_label() == NAV_LABEL for a in actors):
        _spawn(unreal.NavMeshBoundsVolume, (0.0, 0.0, 0.0), label=NAV_LABEL)
    fit_navigation()


def fit_navigation() -> bool:
    """Stretch the level's MixarNavigation volume over everything with
    collision, and let its navigation mesh rebuild while the game runs (a
    door that opens opens the way). False when the level has none."""
    actors = _sub(unreal.EditorActorSubsystem).get_all_level_actors()
    volume = next((a for a in actors if a.get_actor_label() == NAV_LABEL), None)
    if volume is None:
        return False
    lo, hi = [1e9, 1e9, 1e9], [-1e9, -1e9, -1e9]
    for actor in actors:
        if not isinstance(actor, unreal.StaticMeshActor) or actor.get_actor_label() == "Ground":
            continue
        origin, extent = actor.get_actor_bounds(True)
        for i, axis in enumerate("xyz"):
            lo[i] = min(lo[i], getattr(origin, axis) - getattr(extent, axis))
            hi[i] = max(hi[i], getattr(origin, axis) + getattr(extent, axis))
    if lo[0] > hi[0]:  # nothing placed yet: the 60 m around the origin
        lo, hi = [-3000.0, -3000.0, -500.0], [3000.0, 3000.0, 500.0]
    margin = 500.0
    center = [(a + b) / 2 for a, b in zip(lo, hi)]
    size = [b - a + 2 * margin for a, b in zip(lo, hi)]
    volume.set_actor_location(unreal.Vector(*center), False, True)
    # The editor's volume factory builds a 200 cm box brush.
    volume.set_actor_scale3d(unreal.Vector(*[max(s, 400.0) / 200.0 for s in size]))
    nav = unreal.NavigationSystemV1.get_navigation_system(world())
    if nav:
        nav.on_navigation_bounds_updated(volume)
    for actor in _sub(unreal.EditorActorSubsystem).get_all_level_actors():
        if isinstance(actor, unreal.RecastNavMesh):
            actor.set_editor_property("runtime_generation", unreal.RuntimeGenerationType.DYNAMIC)
    unreal.SystemLibrary.execute_console_command(world(), "RebuildNavigation")
    return True


def open_scene(path: str) -> dict:
    path = path.split(".", 1)[0]
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return {"error": f"No level at {path}."}
    reason = _leave_level()
    if reason:
        return {"error": reason}
    if not _sub(unreal.LevelEditorSubsystem).load_level(path):
        return {"error": f"Unreal could not open {path}."}
    return {"scene": level_path()}


# ---------------------------------------------------------------------------
# place
# ---------------------------------------------------------------------------

def _meta(asset, key: str) -> str:
    return str(unreal.EditorAssetLibrary.get_metadata_tag(asset, key) or "")


def _package_meshes(path: str) -> list:
    """The tagged meshes of a package folder, or the one asset ``path``."""
    if unreal.EditorAssetLibrary.does_directory_exist(path):
        found = []
        for asset_path in unreal.EditorAssetLibrary.list_assets(path, recursive=False):
            asset = unreal.EditorAssetLibrary.load_asset(str(asset_path).split(".", 1)[0])
            if isinstance(asset, (unreal.StaticMesh, unreal.SkeletalMesh)) and _meta(asset, "mixar_package"):
                found.append(asset)
        return found
    if unreal.EditorAssetLibrary.does_asset_exist(path):
        asset = unreal.EditorAssetLibrary.load_asset(path)
        if isinstance(asset, (unreal.StaticMesh, unreal.SkeletalMesh)):
            return [asset]
    return []


def _origin(asset) -> list:
    try:
        return [float(v) for v in _meta(asset, "mixar_origin").split(",")][:3] or [0.0, 0.0, 0.0]
    except ValueError:
        return [0.0, 0.0, 0.0]


def _turn(xy, yaw_deg: float):
    a = math.radians(yaw_deg)
    return xy[0] * math.cos(a) - xy[1] * math.sin(a), xy[0] * math.sin(a) + xy[1] * math.cos(a)


def _unique(label: str) -> str:
    taken = {a.get_actor_label() for a in _sub(unreal.EditorActorSubsystem).get_all_level_actors()}
    if label not in taken:
        return label
    n = 2
    while f"{label}_{n}" in taken:
        n += 1
    return f"{label}_{n}"


def _set_body(actor, component, asset) -> None:
    body = _meta(asset, "mixar_body") or "static"
    collision = _meta(asset, "mixar_collision")
    if body == "static" and _meta(asset, "mixar_role") not in MOVING_ROLES:
        component.set_mobility(unreal.ComponentMobility.STATIC)
    else:
        component.set_mobility(unreal.ComponentMobility.MOVABLE)
    if body == "rigid":
        component.set_simulate_physics(True)
    if body == "none" or collision == "none":
        component.set_collision_enabled(unreal.CollisionEnabled.NO_COLLISION)
    if _meta(asset, "mixar_nav") == "ignore" or _meta(asset, "mixar_role") in WALKED_ROLES:
        component.set_editor_property("can_ever_affect_navigation", False)


def _actor_tags(asset) -> list:
    tags = []
    for key in ("mixar_package", "mixar_object", "mixar_role", "mixar_body", "mixar_nav", "mixar_pivot",
                "mixar_light"):
        value = _meta(asset, key)
        if value:
            tags.append(unreal.Name(f"{key}={value}"))
    return tags


def _play_clip(actor, asset, clip: str) -> str:
    """Loop ``clip`` on a character, retargeting a Mannequin clip first.
    Returns the clip played, or raises with the reason."""
    anim = unreal.EditorAssetLibrary.load_asset(clip) if unreal.EditorAssetLibrary.does_asset_exist(clip) else None
    if not isinstance(anim, unreal.AnimSequence):
        raise ValueError(f"No animation at {clip}.")
    skeleton = asset.get_editor_property("skeleton")
    if anim.get_skeleton() != skeleton:
        package = _meta(asset, "mixar_package")
        folder = f"{MIXAR_FOLDER}/{package}"
        target = retarget.retargeted_path(clip, folder, package)
        if not unreal.EditorAssetLibrary.does_asset_exist(target):
            rtg = f"{folder}/RTG_Mannequin_To_{package}"
            if not unreal.EditorAssetLibrary.does_asset_exist(rtg):
                raise ValueError("This character has no retargeter (its package had no Mannequin bone map).")
            retarget.retarget_clips(asset, rtg, [clip], folder, package)
        anim = unreal.EditorAssetLibrary.load_asset(target)
        if not isinstance(anim, unreal.AnimSequence):
            raise ValueError(f"Retargeting {clip} onto the character made nothing; read log.")
        clip = target
    component = actor.skeletal_mesh_component
    component.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    component.set_editor_property("animation_data", unreal.SingleAnimationPlayData(
        anim_to_play=anim, saved_looping=True, saved_playing=True, saved_play_rate=1.0))
    component.set_update_animation_in_editor(True)
    return clip


def place(scene: str, name: str, position, yaw_deg: float, parent: str, animation: str) -> dict:
    reason = refusal()
    if reason:
        return {"error": reason}
    path = scene.split(".", 1)[0]
    if not path.startswith(MIXAR_FOLDER + "/"):
        return {"error": f"place takes a package from import_package (main_scene, under {MIXAR_FOLDER}/)."}
    meshes = _package_meshes(path)
    if not meshes:
        return {"error": f"No Mixar package at {path}; import_package returns main_scene."}
    parent_actor = None
    if parent:
        parent_actor = next((a for a in _sub(unreal.EditorActorSubsystem).get_all_level_actors()
                             if _outliner_path(a) == parent), None)
        if parent_actor is None:
            return {"error": f"No actor at {parent} (paths come from scene_tree)."}
    instance = _unique(name or path.rsplit("/", 1)[-1])
    at = [float(v) for v in (position or [0.0, 0.0, 0.0])][:3]
    folder = f"{INSTANCE_FOLDER}/{instance}"
    placed, clip = [], ""
    with unreal.ScopedEditorTransaction(f"Mixar: place {instance}"):
        try:
            clip = _spawn_package(meshes, at, yaw_deg, instance, folder, parent_actor, animation, placed)
        except Exception as err:  # noqa: BLE001 - a half-placed package is removed again
            if placed:
                _sub(unreal.EditorActorSubsystem).destroy_actors(placed)
            return {"error": f"Placing {instance} failed: {err}"}
    if not placed:
        return {"error": "Unreal spawned nothing for the package."}
    save()
    out = {"node": folder if len(meshes) > 1 else f"{INSTANCE_FOLDER}/{instance}", "actors": len(placed),
           "position": at, "scene": level_path()}
    if clip:
        out["animation"] = clip
    return out


def _spawn_package(meshes, at, yaw_deg, instance, folder, parent_actor, animation, placed) -> str:
    """Spawn one actor per mesh into ``placed``; returns the clip played."""
    clip = ""
    for asset in meshes:
        ox, oy, oz = _origin(asset)
        dx, dy = _turn((ox, oy), yaw_deg)
        location = frames.from_blender([at[0] + dx, at[1] + dy, at[2] + oz])
        rotation = unreal.Rotator(roll=0.0, pitch=0.0, yaw=frames.yaw_from_blender(yaw_deg))
        obj = _meta(asset, "mixar_object") or asset.get_name()
        actor = _sub(unreal.EditorActorSubsystem).spawn_actor_from_object(
            asset, unreal.Vector(*location), rotation)
        if actor is None:
            continue
        actor.set_actor_label(obj if len(meshes) > 1 else instance)
        actor.set_folder_path(folder if len(meshes) > 1 else INSTANCE_FOLDER)
        actor.tags = _actor_tags(asset)
        if isinstance(actor, unreal.StaticMeshActor):
            _set_body(actor, actor.static_mesh_component, asset)
        if parent_actor:
            actor.attach_to_actor(parent_actor, "", unreal.AttachmentRule.KEEP_WORLD,
                                  unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
        placed.append(actor)
        if animation and isinstance(actor, unreal.SkeletalMeshActor):
            clip = _play_clip(actor, asset, animation)
    return clip


def _outliner_path(actor) -> str:
    folder = str(actor.get_folder_path() or "")
    label = actor.get_actor_label()
    return f"{folder}/{label}" if folder and folder != "None" else label


def remove_node(node: str) -> dict:
    """Remove the actor at ``node`` (an outliner path) or every actor in the
    folder ``node`` (a placed package)."""
    reason = refusal()
    if reason:
        return {"error": reason}
    actors = [a for a in _sub(unreal.EditorActorSubsystem).get_all_level_actors()
              if _outliner_path(a) == node or _outliner_path(a).startswith(node.rstrip("/") + "/")]
    if not actors:
        return {"error": f"No actor or folder at {node} (paths come from scene_tree)."}
    with unreal.ScopedEditorTransaction(f"Mixar: remove {node}"):
        _sub(unreal.EditorActorSubsystem).destroy_actors(actors)
    save()
    return {"removed": len(actors), "scene": level_path()}
