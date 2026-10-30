"""The template game's sounds and effects, made with its Blueprints.

- Sounds (``/Game/Mixar/Game/Audio``): the WAVs in the plugin's
  ``Resources/Sounds`` (synthesised by ``scripts/make_sounds.py``), imported
  as SoundWaves; the wind and the music loop.
- Effects (``/Game/Mixar/Game/FX``): Niagara systems made from the engine's
  template bursts (Epic's Niagara toolset), tinted for the game — a gold burst
  for a pickup, a red one for a hit, a big warm one for the win.

``ensure()`` returns {name: object path} for the Blueprints to name; a
missing piece is left out (the game plays without it) and said in the log.
"""

import json
import os

import unreal

from . import MIXAR_FOLDER

AUDIO = f"{MIXAR_FOLDER}/Game/Audio"
FX = f"{MIXAR_FOLDER}/Game/FX"
SOUNDS = ("S_MixarPickup", "S_MixarCheckpoint", "S_MixarHurt", "S_MixarDoor", "S_MixarWin", "S_MixarWind",
          "S_MixarMusic", "S_MixarGunshot", "S_MixarFootstep", "S_MixarReload", "S_MixarDryfire", "S_MixarHitmarker",
          "S_MixarHeadshot", "S_MixarRoundstart")
# Heard in the world (bots' shots and steps): fades with distance, panned.
ATTENUATION = "SA_MixarWorld"
LOOPING = {"S_MixarWind", "S_MixarMusic"}
TEMPLATES = "/Niagara/DefaultAssets/Templates/Systems"
NIAGARA = "NiagaraToolsets.NiagaraToolset_System"
# name: (template system, colour (HDR linear), emitters to tint)
EFFECTS = {
    "NS_MixarPickup": ("RadialBurst", (8.0, 4.6, 0.9), ("OmnidirectionalBurst", "Ribbon_Trail_Leader",
                                                        "RibbonTrailFollower")),
    "NS_MixarHurt": ("SimpleExplosion", (6.0, 0.5, 0.25), ("OmnidirectionalBurst", "SimpleSpriteBurst",
                                                            "UpwardMeshBurst")),
    "NS_MixarWin": ("RadialBurst", (10.0, 7.0, 3.0), ("OmnidirectionalBurst", "Ribbon_Trail_Leader",
                                                       "RibbonTrailFollower")),
    "NS_MixarFlash": ("SimpleExplosion", (16.0, 8.0, 2.5), ("OmnidirectionalBurst", "SimpleSpriteBurst",
                                                          "UpwardMeshBurst")),
    "NS_MixarSparks": ("RadialBurst", (9.0, 6.0, 3.0), ("OmnidirectionalBurst", "Ribbon_Trail_Leader",
                                                         "RibbonTrailFollower")),
    "NS_MixarBlood": ("SimpleExplosion", (0.35, 0.0, 0.0), ("OmnidirectionalBurst", "SimpleSpriteBurst",
                                                             "UpwardMeshBurst")),
}


def _sounds_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))  # <plugin>/Content/Python/mixar_link
    return os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(here))), "Resources", "Sounds")


def _path(folder: str, name: str) -> str:
    return f"{folder}/{name}.{name}"


def _sounds() -> dict:
    found = {}
    tasks = []
    for name in SOUNDS:
        source = os.path.join(_sounds_dir(), name + ".wav")
        if not os.path.isfile(source):
            unreal.log_warning(f"[Mixar Link] the sound {name}.wav is missing from the plugin")
            continue
        task = unreal.AssetImportTask()
        task.filename = source
        task.destination_path = AUDIO
        task.destination_name = name
        task.replace_existing = True
        task.automated = True
        task.save = True
        tasks.append(task)
    if tasks:
        unreal.AssetToolsHelpers.get_asset_tools().import_asset_tasks(tasks)
    for name in SOUNDS:
        wave = unreal.load_asset(f"{AUDIO}/{name}")
        if not isinstance(wave, unreal.SoundWave):
            continue
        if name in LOOPING:
            wave.set_editor_property("looping", True)
            unreal.EditorAssetLibrary.save_loaded_asset(wave, False)
        found[name] = _path(AUDIO, name)
    return found


def _epic(toolset: str, tool: str, args: dict):
    """Call one of Epic's toolset tools in process (they answer at once)."""
    result = unreal.ToolsetRegistry.execute_tool(toolset, tool, json.dumps(args))
    if not result.is_complete:
        raise RuntimeError(f"{tool} did not answer at once")
    if result.error:
        raise RuntimeError(str(result.error))
    return json.loads(result.value) if result.value else None


def _effects() -> dict:
    found = {}
    for name, (template, colour, emitters) in EFFECTS.items():
        path = f"{FX}/{name}"
        try:
            if not unreal.EditorAssetLibrary.does_asset_exist(path):
                _epic(NIAGARA, "CreateNiagaraSystem", {
                    "assetName": name, "assetPath": FX,
                    "templateSystem": {"refPath": _path(TEMPLATES, template)}})
            r, g, b = colour
            for emitter in emitters:
                _epic(NIAGARA, "SetStackInputData", {
                    "stackInputRef": {"system": {"refPath": _path(FX, name)}, "emitterName": emitter,
                                      "scriptName": "ParticleSpawnScript", "moduleName": "InitializeParticle",
                                      "rendererIndex": -1, "inputNameStack": ["Color"]},
                    "inputData": {"struct": {"refPath": "/Script/CoreUObject.LinearColor"},
                                  "value": {"r": r, "g": g, "b": b, "a": 1.0}}})
            unreal.EditorAssetLibrary.save_asset(path, False)
        except Exception as exc:  # noqa: BLE001 - the game plays without the effect
            unreal.log_warning(f"[Mixar Link] the effect {name} was not made: {exc}")
            continue
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            found[name] = _path(FX, name)
    return found


def _attenuation() -> dict:
    path = f"{AUDIO}/{ATTENUATION}"
    try:
        asset = unreal.load_asset(path)
        if asset is None:
            asset = unreal.AssetToolsHelpers.get_asset_tools().create_asset(
                ATTENUATION, AUDIO, unreal.SoundAttenuation, unreal.SoundAttenuationFactory())
        settings = asset.get_editor_property("attenuation")
        for key, value in (("attenuate", True), ("spatialize", True), ("falloff_distance", 6000.0)):
            settings.set_editor_property(key, value)
        settings.set_editor_property("attenuation_shape_extents", unreal.Vector(300.0, 0.0, 0.0))
        asset.set_editor_property("attenuation", settings)
        unreal.EditorAssetLibrary.save_loaded_asset(asset, False)
    except Exception as exc:  # noqa: BLE001 - sounds then play unattenuated
        unreal.log_warning(f"[Mixar Link] the sound attenuation was not made: {exc}")
        return {}
    return {ATTENUATION: _path(AUDIO, ATTENUATION)}


def ensure() -> dict:
    return {**_sounds(), **_attenuation(), **_effects()}
