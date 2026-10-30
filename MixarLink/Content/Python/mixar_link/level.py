"""Levels: make, open and save them, and put packages into them.

Levels Mixar makes live under ``/Game/Mixar/Levels``. In ``plugin`` mode
(``config.mode()``) Mixar edits only levels under ``/Game/Mixar`` and never
the project's settings; in ``owned`` mode (a game Mixar made) it edits any.

``place`` puts a package together: one actor per object at its origin, moved
by ``position`` and turned by ``yaw_deg`` about the package's own origin,
under the outliner folder ``Mixar/<instance>``. Actors carry the objects'
tags as actor tags (``mixar_role=pickup`` …), take their mobility and
physics from ``mixar_body``, and a rigged character can play a Mannequin clip
(retargeted on first use). A rigged humanoid tagged ``mixar_role=player``
in a template level gets the Mannequin's idle, run and fall clips retargeted
onto it: the template game plays as it instead of the Mannequin (elsewhere it
is an ordinary character).

In a ``shooter`` level a rigged ``player`` / ``ally`` / ``enemy`` becomes a
team's model and a ``weapon`` the rifle everyone holds (``shooter``).

``new_scene`` lights a level by ``look`` (day, sunset, dawn, night, overcast):
sun, sky atmosphere, sky light, volumetric clouds, height fog and a post
process (bloom, exposure, grading). ``floating`` sinks the planet's ground and
the cloud layer under the level, for islands in the sky.
"""

import math
import os
import re

import unreal

from . import MIXAR_FOLDER, config, frames, game, retarget, shooter

LEVELS = f"{MIXAR_FOLDER}/Levels"
INSTANCE_FOLDER = "Mixar"
MAPS_SECTION = "[/Script/EngineSettings.GameMapsSettings]"
GROUND_SIZE_M = 60.0
_UNARMED = "/Game/Characters/Mannequins/Anims/Unarmed"
# The player's clips, retargeted from the Mannequin's: game info variable -> clip.
PLAYER_CLIPS = {"IdleAnim": f"{_UNARMED}/MM_Idle", "RunAnim": f"{_UNARMED}/Jog/MF_Unarmed_Jog_Fwd",
                "FallAnim": f"{_UNARMED}/Jump/MM_Fall_Loop"}
# look: (sun pitch, sun yaw, lux, sun colour, sky light, fog density, fog colour, bloom, exposure bias)
LOOKS = {
    "day": (-48.0, -35.0, 10.0, (1.0, 0.97, 0.92), 1.0, 0.006, (0.14, 0.19, 0.27), 0.6, 0.0),
    "sunset": (-11.0, -60.0, 8.0, (1.0, 0.72, 0.45), 1.0, 0.008, (0.3, 0.19, 0.12), 0.9, 0.4),
    "dawn": (-9.0, 110.0, 6.0, (1.0, 0.78, 0.68), 1.0, 0.01, (0.26, 0.2, 0.22), 0.8, 0.4),
    "night": (-40.0, -20.0, 0.8, (0.62, 0.7, 1.0), 0.35, 0.01, (0.03, 0.04, 0.08), 0.7, 1.2),
    "overcast": (-62.0, 10.0, 3.5, (0.9, 0.92, 0.96), 1.4, 0.02, (0.2, 0.21, 0.23), 0.4, 0.3),
}
FLOATING_GROUND_KM = 6.0
NAV_LABEL = "MixarNavigation"
# Roles the template game moves at run time, so their actors are Movable.
MOVING_ROLES = {"pickup", "door", "hazard", "enemy"}
# Roles that never shape the navigation mesh: the player walks through the
# first ones, and dodges hazards and enemies rather than routing around them
# (a moving one would carve and re-carve the mesh, and paths would come and go).
WALKED_ROLES = {"pickup", "goal", "checkpoint", "trigger", "spawn", "hazard", "enemy", "player", "ally", "weapon"}


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


def _set(obj, **values) -> None:
    """Set what this engine version has; a renamed property is skipped."""
    for key, value in values.items():
        try:
            obj.set_editor_property(key, value)
        except Exception:  # noqa: BLE001
            unreal.log_warning(f"[Mixar Link] {obj.get_name()} has no {key}")


def _post_process(bloom: float, exposure: float) -> None:
    volume = _spawn(unreal.PostProcessVolume, label="PostProcess")
    volume.set_editor_property("unbound", True)
    settings = volume.get_editor_property("settings")
    for key, value in (("bloom_intensity", bloom), ("auto_exposure_bias", exposure), ("vignette_intensity", 0.35),
                       ("color_saturation", unreal.Vector4(1.08, 1.08, 1.08, 1.0)),
                       ("color_contrast", unreal.Vector4(1.05, 1.05, 1.05, 1.0)),
                       ("film_toe", 0.6)):
        try:
            settings.set_editor_property("override_" + key, True)
            settings.set_editor_property(key, value)
        except Exception:  # noqa: BLE001 - a setting this engine lacks
            unreal.log_warning(f"[Mixar Link] post process has no {key}")
    volume.set_editor_property("settings", settings)


def _defaults(ground: bool, player_position, look: str = "", floating: bool = False) -> None:
    pitch, yaw, lux, colour, sky_level, fog_density, fog_colour, bloom, exposure = LOOKS.get(look, LOOKS["day"])
    sun = _spawn(unreal.DirectionalLight, (0, 0, 1000), pitch=pitch, yaw=yaw, label="Sun")
    light = sun.light_component
    _set(light, atmosphere_sun_light=True, intensity=lux, light_color=unreal.Color(*[int(c * 255) for c in colour], 255))
    sky = _spawn(unreal.SkyAtmosphere, label="SkyAtmosphere")
    skylight = _spawn(unreal.SkyLight, (0, 0, 500), label="SkyLight")
    skylight.light_component.set_editor_property("real_time_capture", True)
    skylight.light_component.set_mobility(unreal.ComponentMobility.MOVABLE)
    _set(skylight.light_component, intensity=sky_level)
    fog = _spawn(unreal.ExponentialHeightFog, label="Fog").get_component_by_class(unreal.ExponentialHeightFogComponent)
    _set(fog, fog_density=fog_density, fog_height_falloff=0.12, enable_volumetric_fog=True,
         fog_inscattering_luminance=unreal.LinearColor(*fog_colour, 1.0),
         directional_inscattering_luminance=unreal.LinearColor(*colour, 1.0))
    clouds = _spawn(unreal.VolumetricCloud, label="Clouds")
    if floating:  # the ground is far below and the cloud tops sit under the level
        _set(sky.get_component_by_class(unreal.SkyAtmosphereComponent),
             transform_mode=unreal.SkyAtmosphereTransformMode.PLANET_TOP_AT_COMPONENT_TRANSFORM)
        sky.set_actor_location(unreal.Vector(0.0, 0.0, -FLOATING_GROUND_KM * 100000.0), False, True)
        _set(clouds.get_component_by_class(unreal.VolumetricCloudComponent),
             layer_bottom_altitude=FLOATING_GROUND_KM - 2.5, layer_height=1.8)
        _set(fog, fog_height_falloff=0.08, fog_density=fog_density * 0.6)
    _post_process(bloom, exposure)
    start = frames.from_blender(player_position) if player_position else (0.0, 0.0, 100.0)
    _spawn(unreal.PlayerStart, start, label="PlayerStart")
    if ground:
        floor = _spawn(unreal.StaticMeshActor, (0, 0, -5), label="Ground")
        floor.static_mesh_component.set_static_mesh(unreal.EditorAssetLibrary.load_asset("/Engine/BasicShapes/Cube"))
        floor.set_actor_scale3d(unreal.Vector(GROUND_SIZE_M, GROUND_SIZE_M, 0.1))


def new_scene(name: str, set_as_main: bool, with_defaults: bool, overwrite: bool, ground: bool,
              player_position, template: str = "", look: str = "", floating: bool = False, title: str = "",
              objective: str = "") -> dict:
    path = f"{LEVELS}/{name}"
    game_mode = None
    if template:
        classes = game.ensure(template)
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
        _defaults(ground, player_position, look, floating)
    elif ground:
        _defaults(True, player_position, look, floating)
    if game_mode is not None:
        _make_game(game_mode, player_position, title or name.replace("_", " "), objective)
    save()
    out = {"scene": path, "main": False, "look": look or "day"}
    if template:
        out["template"] = template
        out["game_mode"] = game_mode.get_path_name().split(".", 1)[0]
    if set_as_main:
        before = main_level()
        note = set_main(path)
        out["main"] = not note
        if note:
            out["note"] = note
        elif before and before != path:  # say so: the project now opens this level instead
            out["replaced_main"] = before
    return out


def _make_game(game_mode, player_position, title: str, objective: str) -> None:
    """The level runs ``game_mode`` (World Settings override), has a
    PlayerStart, a navigation volume playtests route by and its game info
    (title, objective, music)."""
    world().get_world_settings().set_editor_property("default_game_mode", game_mode)
    actors = _sub(unreal.EditorActorSubsystem).get_all_level_actors()
    if not any(isinstance(a, unreal.PlayerStart) for a in actors):
        start = frames.from_blender(player_position) if player_position else (0.0, 0.0, 100.0)
        _spawn(unreal.PlayerStart, start, label="PlayerStart")
    if not any(a.get_actor_label() == NAV_LABEL for a in actors):
        _spawn(unreal.NavMeshBoundsVolume, (0.0, 0.0, 0.0), label=NAV_LABEL)
    info_class = game.info_class()
    if info_class is not None and not any(a.get_class() == info_class for a in actors):
        info = _spawn(info_class, (0.0, 0.0, 0.0), label="GameInfo")
        info.set_editor_property("Title", title)
        info.set_editor_property("Objective", objective)
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
                "mixar_light", "mixar_team"):
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
        retarget.lock_root(anim)
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
        elif isinstance(actor, unreal.SkeletalMeshActor) and _meta(asset, "mixar_role") in WALKED_ROLES:
            actor.skeletal_mesh_component.set_editor_property("can_ever_affect_navigation", False)
        if parent_actor:
            actor.attach_to_actor(parent_actor, "", unreal.AttachmentRule.KEEP_WORLD,
                                  unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
        placed.append(actor)
        role = _meta(asset, "mixar_role")
        if role in ("player", "ally", "enemy", "weapon") and shooter.is_shooter_level(world()):
            if role == "weapon":
                shooter.weapon(actor, asset)
            elif isinstance(actor, unreal.SkeletalMeshActor):
                clip = shooter.character(actor, asset, role)
        elif isinstance(actor, unreal.SkeletalMeshActor) and role == "player" and _game_info():
            clip = _player_anim(actor, asset)
        elif animation and isinstance(actor, unreal.SkeletalMeshActor):
            clip = _play_clip(actor, asset, animation)
    return clip


def _game_info():
    """The open level's BP_MixarGameInfo (a template level has one), or None."""
    info_class = game.info_class()
    if info_class is None:
        return None
    return next((a for a in _sub(unreal.EditorActorSubsystem).get_all_level_actors()
                 if a.get_class() == info_class), None)


def _player_anim(actor, asset) -> str:
    """The Mannequin's idle, run and fall clips retargeted onto a player
    character and handed to the level's game info; the template game plays
    them as the player moves. The stand-in loops the idle."""
    info = _game_info()
    package = _meta(asset, "mixar_package")
    folder = f"{MIXAR_FOLDER}/{package}"
    rtg = f"{folder}/RTG_Mannequin_To_{package}"
    if not unreal.EditorAssetLibrary.does_asset_exist(rtg):
        raise ValueError("A player character needs a humanoid rig with a Mannequin bone map; this package has "
                         "none (rig it as a biped, then export again).")
    missing = [c for c in PLAYER_CLIPS.values()
               if not unreal.EditorAssetLibrary.does_asset_exist(retarget.retargeted_path(c, folder, package))]
    if missing:
        retarget.retarget_clips(asset, rtg, missing, folder, package)
    for key, clip in PLAYER_CLIPS.items():
        anim = unreal.EditorAssetLibrary.load_asset(retarget.retargeted_path(clip, folder, package))
        if not isinstance(anim, unreal.AnimSequence):
            raise ValueError(f"Retargeting {clip} onto the character made nothing; read log.")
        info.set_editor_property(key, anim)
    return _play_clip(actor, asset, PLAYER_CLIPS["IdleAnim"])


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
