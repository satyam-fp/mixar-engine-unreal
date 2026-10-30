"""Shooter levels: characters and weapons placed into a ``shooter`` template level.

``place`` hands these here when the open level runs the shooter GameMode:

- a rigged humanoid with ``mixar_role`` ``player`` / ``ally`` / ``enemy``
  (team ``mixar_team`` ct / t, else the player's and their allies' team is
  CT and enemies are T) becomes that team's model: the UE5 Mannequin's rifle
  set (``shooter_spec.ANIMS``) is retargeted onto it, and the level's game
  info gets its mesh, clips, hand and head bones, the weapon grip and (CT)
  the view-model offset;
- a ``mixar_role=weapon`` mesh becomes the rifle every character holds.

Both stay in the level as hidden stand-ins (tag ``mixar_shooter_standin``).

The grip is measured, not guessed, by the game itself a moment after a
character spawns: in its live aiming pose the barrel runs from the right hand
(on the grip) toward the left hand (on the handguard), level with the world's
up (``MixarGrip``). The weapon package's convention makes that exact: its
origin is the pistol grip where the right hand closes, its barrel points to
Blender -Y (the same front a character faces) and its top is up. The view
model is placed the same way: its eyes go to ``ViewEye`` from the camera (a
little behind, right and low), so the rifle shows lower right as in a
first-person shooter; the level's GameInfo ViewEye tunes it.
"""

import json

import unreal

from . import MIXAR_FOLDER, game, retarget, shooter_spec

STANDIN_TAG = "mixar_shooter_standin"


def _sub(cls):
    return unreal.get_editor_subsystem(cls)


def is_shooter_level(world) -> bool:
    shooter = game._class("BP_MixarShooterGameMode")  # noqa: SLF001
    settings = world.get_world_settings() if world else None
    mode = settings.get_editor_property("default_game_mode") if settings else None
    return bool(shooter and mode and unreal.MathLibrary.class_is_child_of(mode, shooter))


def _info():
    info_class = game.info_class()
    return next((a for a in _sub(unreal.EditorActorSubsystem).get_all_level_actors()
                 if info_class is not None and a.get_class() == info_class), None)


def _meta(asset, key: str) -> str:
    return str(unreal.EditorAssetLibrary.get_metadata_tag(asset, key) or "")


def _bones(asset) -> dict:
    try:
        return json.loads(_meta(asset, "mixar_bone_map") or "{}")
    except ValueError:
        return {}


def _clips(asset, package: str) -> list:
    """The rifle set on this character's skeleton (retargeted on first use)."""
    folder = f"{MIXAR_FOLDER}/{package}"
    rtg = f"{folder}/RTG_Mannequin_To_{package}"
    if not unreal.EditorAssetLibrary.does_asset_exist(rtg):
        raise ValueError("A shooter character needs a humanoid rig with a Mannequin bone map; this package has "
                         "none (rig it as a biped, then export again).")
    missing = [c for c in shooter_spec.ANIMS if unreal.EditorAssetLibrary.does_asset_exist(c)
               and not unreal.EditorAssetLibrary.does_asset_exist(retarget.retargeted_path(c, folder, package))]
    if missing:
        retarget.retarget_clips(asset, rtg, missing, folder, package)
    out = []
    for clip in shooter_spec.ANIMS:
        anim = unreal.load_asset(retarget.retargeted_path(clip, folder, package))
        retarget.lock_root(anim)  # clips retargeted before 0.5 too
        if not isinstance(anim, unreal.AnimSequence):
            raise ValueError(f"The project has no {clip}, or retargeting it made nothing (read log). The shooter "
                             "uses the Third Person template's rifle animations.")
        out.append(anim)
    for anim in out:
        unreal.EditorAssetLibrary.save_loaded_asset(anim, False)
    return out


def character(actor, asset, role: str) -> str:
    """Make a placed character a team's model; returns the clip it loops."""
    info = _info()
    if info is None:
        raise ValueError("Place shooter characters into a level made with new_scene(template=\"shooter\").")
    player_team = str(info.get_editor_property("PlayerTeam") or "ct")
    team = _meta(asset, "mixar_team") or (player_team if role in ("player", "ally")
                                          else ("t" if player_team == "ct" else "ct"))
    prefix = "CT" if team == "ct" else "T"
    package = _meta(asset, "mixar_package")
    bones = _bones(asset)
    clips = _clips(asset, package)
    info.set_editor_property(f"{prefix}Mesh", asset)
    info.set_editor_property(f"{prefix}Anims", clips)
    if not bones.get("hand_r") or not bones.get("hand_l"):
        raise ValueError("The character's bone map has no hands (hand_r / hand_l); rig it as a humanoid biped.")
    info.set_editor_property(f"{prefix}Hand", unreal.Name(bones["hand_r"]))
    info.set_editor_property(f"{prefix}LeftHand", unreal.Name(bones["hand_l"]))
    info.set_editor_property(f"{prefix}Head", unreal.Name(bones.get("head", "head")))
    if prefix == "CT":
        if info.get_editor_property("ViewEye") == unreal.Vector(0.0, 0.0, 0.0):
            info.set_editor_property("ViewEye", unreal.Vector(*shooter_spec.VIEW_EYE))
        hide = [bones[k] for k in ("head", "thigh_l", "thigh_r") if bones.get(k)]
        info.set_editor_property("CTHide", [unreal.Name(b) for b in hide])
    _standin(actor)
    component = actor.skeletal_mesh_component
    component.set_animation_mode(unreal.AnimationMode.ANIMATION_SINGLE_NODE)
    component.set_editor_property("animation_data", unreal.SingleAnimationPlayData(
        anim_to_play=clips[0], saved_looping=True, saved_playing=True, saved_play_rate=1.0))
    return clips[0].get_path_name().split(".", 1)[0]


def weapon(actor, asset) -> None:
    """Make a placed mesh the rifle every character holds."""
    info = _info()
    if info is None:
        raise ValueError("Place the weapon into a level made with new_scene(template=\"shooter\").")
    info.set_editor_property("Weapon", asset)
    box = asset.get_bounding_box()
    info.set_editor_property("WeaponReach", float(max(box.max.y, 10.0)))
    _standin(actor)


def _standin(actor) -> None:
    tags = list(actor.tags)
    if unreal.Name(STANDIN_TAG) not in tags:
        tags.append(unreal.Name(STANDIN_TAG))
        actor.tags = tags
