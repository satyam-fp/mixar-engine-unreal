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
          "S_MixarHeadshot", "S_MixarRoundstart", "S_MixarBeep", "S_MixarPlant", "S_MixarDefuse", "S_MixarExplosion")
# Heard in the world (bots' shots and steps): fades with distance, panned.
ATTENUATION = "SA_MixarWorld"
LOOPING = {"S_MixarWind", "S_MixarMusic"}
TEMPLATES = "/Niagara/DefaultAssets/Templates/Systems"
NIAGARA = "NiagaraToolsets.NiagaraToolset_System"
# name: (template system, colour (HDR linear), emitters to tint, emitters to
# remove, {(emitter, InitializeParticle input): float}). The template systems
# are sized in world units (a spawn's Scale does not shrink their sprites), so
# sizes and lifetimes are set here.
_RIBBONS = ("RibbonTrailFollower", "Ribbon_Trail_Leader")
_BURST = "OmnidirectionalBurst"


def _sized(size, life):
    return {(_BURST, "Uniform Sprite Size Min"): size[0], (_BURST, "Uniform Sprite Size Max"): size[1],
            (_BURST, "Lifetime Min"): life[0], (_BURST, "Lifetime Max"): life[1]}


EFFECTS = {
    "NS_MixarPickup": ("RadialBurst", (8.0, 4.6, 0.9), (_BURST,) + _RIBBONS, (), _sized((2.0, 6.0), (0.5, 1.2))),
    "NS_MixarHurt": ("RadialBurst", (6.0, 0.4, 0.2), (_BURST,), _RIBBONS, _sized((4.0, 10.0), (0.25, 0.5))),
    "NS_MixarWin": ("RadialBurst", (10.0, 7.0, 3.0), (_BURST,) + _RIBBONS, (), _sized((3.0, 8.0), (1.0, 2.0))),
    "NS_MixarFlash": ("RadialBurst", (18.0, 9.0, 2.5), (_BURST,), _RIBBONS, _sized((5.0, 12.0), (0.03, 0.06))),
    "NS_MixarSparks": ("RadialBurst", (9.0, 6.0, 3.0), (_BURST,), _RIBBONS, _sized((1.0, 2.5), (0.12, 0.3))),
    "NS_MixarBlood": ("RadialBurst", (0.35, 0.01, 0.01), (_BURST,), _RIBBONS, _sized((3.0, 7.0), (0.2, 0.4))),
    "NS_MixarBlink": ("RadialBurst", (14.0, 0.3, 0.15), (_BURST,), _RIBBONS, _sized((1.2, 2.2), (0.06, 0.1))),
    "NS_MixarExplosion": ("RadialBurst", (14.0, 5.0, 1.2), (_BURST,), _RIBBONS, _sized((80.0, 220.0), (0.6, 1.8))),
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


def _input(system: str, emitter: str, name: str, struct: str, value: dict) -> None:
    _epic(NIAGARA, "SetStackInputData", {
        "stackInputRef": {"system": {"refPath": system}, "emitterName": emitter, "scriptName": "ParticleSpawnScript",
                          "moduleName": "InitializeParticle", "rendererIndex": -1, "inputNameStack": [name]},
        "inputData": {"struct": {"refPath": struct}, "value": value}})


def _effects() -> dict:
    found = {}
    for name, (template, colour, tinted, removed, floats) in EFFECTS.items():
        path, system = f"{FX}/{name}", _path(FX, name)
        try:
            if unreal.EditorAssetLibrary.does_asset_exist(path):  # remade: its settings may have changed
                unreal.EditorAssetLibrary.delete_asset(path)
            _epic(NIAGARA, "CreateNiagaraSystem", {
                "assetName": name, "assetPath": FX, "templateSystem": {"refPath": _path(TEMPLATES, template)}})
            for emitter in removed:
                _epic(NIAGARA, "RemoveEmitter", {"emitterToRemove": {
                    "system": {"refPath": system}, "emitterName": emitter, "scriptName": "", "moduleName": "",
                    "rendererIndex": -1, "inputNameStack": []}})
            r, g, b = colour
            for emitter in tinted:
                _input(system, emitter, "Color", "/Script/CoreUObject.LinearColor", {"r": r, "g": g, "b": b, "a": 1.0})
            for (emitter, key), value in floats.items():
                _input(system, emitter, key, "/Script/Niagara.NiagaraFloat", {"value": float(value)})
            unreal.EditorAssetLibrary.save_asset(path, False)
        except Exception as exc:  # noqa: BLE001 - the game plays without the effect
            unreal.log_warning(f"[Mixar Link] the effect {name} was not made: {exc}")
            continue
        if unreal.EditorAssetLibrary.does_asset_exist(path):
            found[name] = system
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
