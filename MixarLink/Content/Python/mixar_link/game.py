"""The template game's Blueprints, built from ``game_spec`` on first use.

``ensure()`` makes (or, after a Mixar Link upgrade, rebuilds in place) under
``/Game/Mixar/Game``:

- ``BP_MixarGameMode`` — the rules (third person);
- ``BP_MixarGameMode_TopDown`` / ``BP_MixarGameMode_Platformer`` — children
  that only change ``Template`` (camera and movement);
- ``BP_MixarHUD`` — collected count and the win / lose banner.

They are ordinary Blueprints in the project, so a packaged game carries them.
The graphs are written with Epic's EditorToolset (``BlueprintTools``): its
graph DSL is the same one the ``blueprint`` tool hands the agent. The parent
is the project's third-person GameMode (``/Game/ThirdPerson``), which brings
the player character and its Enhanced Input set-up.
"""

import re

import unreal

from . import ADAPTER_VERSION, MIXAR_FOLDER, game_spec

GAME_FOLDER = f"{MIXAR_FOLDER}/Game"
VERSION_TAG = "mixar_game_version"
CHILDREN = {"top_down": "BP_MixarGameMode_TopDown", "platformer": "BP_MixarGameMode_Platformer"}


def tools():
    """Epic's BlueprintTools, or None when the EditorToolset plugin is off."""
    try:
        from editor_toolset.toolsets.blueprint import BlueprintTools  # noqa: PLC0415
    except ImportError:
        return None
    return BlueprintTools


def _path(name: str) -> str:
    return f"{GAME_FOLDER}/{name}"


def _class(name: str):
    # unreal.load_class, not EditorAssetLibrary: that refuses to work while the game runs.
    return unreal.load_class(None, f"{_path(name)}.{name}_C")


def _current(name: str) -> bool:
    asset = unreal.EditorAssetLibrary.load_asset(_path(name)) \
        if unreal.EditorAssetLibrary.does_asset_exist(_path(name)) else None
    return bool(asset) and unreal.EditorAssetLibrary.get_metadata_tag(asset, VERSION_TAG) == ADAPTER_VERSION


def _blueprint(bt, name: str, parent_class):
    """The Blueprint at ``name``, made when missing. An existing one is
    rewritten in place by ``_apply``, so levels that use it keep it."""
    path = _path(name)
    if not unreal.EditorAssetLibrary.does_asset_exist(path):
        return bt.create(GAME_FOLDER, name, parent_class)
    return unreal.EditorAssetLibrary.load_asset(path)


def _apply(bt, bp, spec: dict) -> None:
    """Variables and function parameters (missing ones added), function bodies
    and events (rewritten: a write replaces the forms it names), compiled.

    Graphs are never removed: a function graph removed and added again under
    its old name comes back renamed (``Name_0``) and every call to it breaks.
    """
    have = set(bt.list_variables(bp))
    for var in spec.get("variables", ()):
        if var[0] not in have:
            container = getattr(_container(), var[2]) if len(var) > 2 else None
            bt.add_variable(bp, var[0], var[1], None, container)
    for name, cls, container in spec.get("object_variables", ()):
        if name not in have:
            bt.add_object_variable(bp, name, unreal.load_class(None, cls), None,
                                   getattr(_container(), container) if container else None)
    present = {g.get_name(): g for g in bt.list_graphs(bp)}
    graphs = {}
    for fname, params, outs, _ in spec.get("functions", ()):
        graph = present.get(fname)
        if graph is None:  # a leftover of an older rebuild: Name_0 → Name
            stray = next((g for n, g in present.items() if re.fullmatch(rf"{fname}_[0-9]+", n)), None)
            if stray is not None:
                unreal.BlueprintEditorLibrary.rename_graph(stray, fname)
                graph = stray
        if graph is None:
            graph = bt.add_function_graph(bp, fname)
        graphs[fname] = graph
        for pname, ptype, is_object in params:
            if bt._param_name_exists(graph, pname, True):
                continue
            if is_object:
                bt.add_object_function_param(graph, pname, unreal.load_class(None, ptype), True, None)
            else:
                bt.add_function_param(graph, pname, ptype, True, None)
        for pname, ptype in outs:
            if not bt._param_name_exists(graph, pname, False):
                bt.add_function_param(graph, pname, ptype, False, None)
    if graphs:  # calls between them resolve once the class knows them
        bt.compile_blueprint(bp, False)
    for fname, _, _, dsl in spec.get("functions", ()):
        bt.write_graph_dsl(graphs[fname], dsl)
    if spec.get("events"):
        bt.write_graph_dsl(unreal.BlueprintEditorLibrary.find_event_graph(bp), spec["events"])
    bt.compile_blueprint(bp, False)
    _verify(bt, bp, spec)


def _verify(bt, bp, spec: dict) -> None:
    """Raise unless every function and event the spec names is in the graphs."""
    names = {g.get_name() for g in bt.list_graphs(bp)}
    missing = [f[0] for f in spec.get("functions", ()) if f[0] not in names]
    events = bt.read_graph_dsl(unreal.BlueprintEditorLibrary.find_event_graph(bp)) if spec.get("events") else ""
    missing += [e for e in re.findall(r"\(event (\w+)", spec.get("events", "")) if f"(event {e}" not in events]
    if missing:
        raise RuntimeError(f"{bp.get_name()} is missing {', '.join(missing)} after the build")


def _container():
    from editor_toolset.toolsets.blueprint import ContainerType  # noqa: PLC0415
    return ContainerType


def _stamp(name: str) -> None:
    asset = unreal.EditorAssetLibrary.load_asset(_path(name))
    unreal.EditorAssetLibrary.set_metadata_tag(asset, VERSION_TAG, ADAPTER_VERSION)
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)


def ensure() -> dict:
    """{template: GameMode class path} for every template, or {"error"}."""
    names = [game_spec.GAME_MODE["name"], game_spec.HUD["name"], *CHILDREN.values()]
    if all(_current(n) for n in names):
        return _classes()
    bt = tools()
    if bt is None:
        return {"error": "The template game needs Unreal's EditorToolset plugin (Edit > Plugins > "
                         "EditorToolset, then restart the editor)."}
    parent = unreal.EditorAssetLibrary.load_blueprint_class(game_spec.GAME_MODE["parent"].rsplit(".", 1)[0])
    if parent is None:
        return {"error": "The template game builds on the project's third-person game "
                         "(/Game/ThirdPerson/Blueprints/BP_ThirdPersonGameMode), which this project has "
                         "not got. A game Mixar made from the Third Person template has it; here, build "
                         "the game's own Blueprints with the blueprint tool."}
    try:
        gm = _blueprint(bt, game_spec.GAME_MODE["name"], parent)
        _apply(bt, gm, game_spec.GAME_MODE)
        hud = _blueprint(bt, game_spec.HUD["name"], unreal.HUD.static_class())
        _apply(bt, hud, game_spec.HUD)
        gm_class = _class(game_spec.GAME_MODE["name"])
        unreal.get_default_object(gm_class).set_editor_property("hud_class", _class(game_spec.HUD["name"]))
        bt.compile_blueprint(gm, False)
        for template, name in CHILDREN.items():
            if not unreal.EditorAssetLibrary.does_asset_exist(_path(name)):
                bt.create(GAME_FOLDER, name, gm_class)
            child = unreal.EditorAssetLibrary.load_asset(_path(name))
            bt.compile_blueprint(child, False)
            unreal.get_default_object(_class(name)).set_editor_property(
                "Template", game_spec.TEMPLATES[template])
            bt.compile_blueprint(child, False)
    except Exception as exc:  # noqa: BLE001 - a build that fails says why
        return {"error": f"Building the template game failed: {exc}"}
    for name in names:
        _stamp(name)
    return _classes()


def _classes() -> dict:
    return {"third_person": _class(game_spec.GAME_MODE["name"]),
            **{t: _class(n) for t, n in CHILDREN.items()}}


def game_mode(world):
    """The running game's Mixar GameMode (a BP_MixarGameMode), or None."""
    gm = unreal.GameplayStatics.get_game_mode(world) if world else None
    base = _class(game_spec.GAME_MODE["name"])
    if gm is None or base is None or not unreal.MathLibrary.class_is_child_of(gm.get_class(), base):
        return None
    return gm
