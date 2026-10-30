"""The template game's Blueprints, built from ``game_spec`` on first use.

``ensure()`` makes (or, after a Mixar Link upgrade, rebuilds in place) under
``/Game/Mixar/Game``:

- ``BP_MixarGameMode`` — the rules (third person);
- ``BP_MixarGameMode_TopDown`` / ``BP_MixarGameMode_Platformer`` — children
  that only change ``Template`` (camera and movement);
- ``BP_MixarHUD`` — title card, count, time, hit flash and end screen;
- ``BP_MixarGameInfo`` — a level's title, objective and music / wind
  switches (one per level, made by ``new_scene``);
- the sounds and effects of ``game_assets``.

They are ordinary Blueprints in the project, so a packaged game carries them.
The graphs are written with Epic's EditorToolset (``BlueprintTools``): its
graph DSL is the same one the ``blueprint`` tool hands the agent. The parent
is the project's third-person GameMode (``/Game/ThirdPerson``), which brings
the player character and its Enhanced Input set-up.
"""

import hashlib
import re

import unreal

from . import ADAPTER_VERSION, MIXAR_FOLDER, game_assets, game_spec, shooter_spec

GAME_FOLDER = f"{MIXAR_FOLDER}/Game"
VERSION_TAG = "mixar_game_version"
CHILDREN = {"top_down": "BP_MixarGameMode_TopDown", "platformer": "BP_MixarGameMode_Platformer"}


def _build_id(name: str = "") -> str:
    """The release plus the game's own sources: a changed spec rebuilds (the
    shooter's Blueprints also hash its spec)."""
    digest = hashlib.sha1()
    for module in (game_spec, game_assets) + ((shooter_spec,) if name in SHOOTER_NAMES else ()):
        with open(module.__file__, "rb") as fh:
            digest.update(fh.read())
    return f"{ADAPTER_VERSION}+{digest.hexdigest()[:10]}"


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
    return bool(asset) and unreal.EditorAssetLibrary.get_metadata_tag(asset, VERSION_TAG) == _build_id(name)


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
    graphs = _declare(bt, bp, spec)
    if graphs:  # calls between them resolve once the class knows them
        bt.compile_blueprint(bp, False)
    _write(bt, bp, spec, graphs)


def _declare(bt, bp, spec: dict) -> dict:
    """Variables, components and function graphs with their parameters (the
    missing ones added); returns {function: graph}."""
    have = set(bt.list_variables(bp))
    for var in spec.get("variables", ()):
        if var[0] not in have:
            container = getattr(_container(), var[2]) if len(var) > 2 else None
            bt.add_variable(bp, var[0], var[1], None, container)
        if spec.get("editable"):
            bt.set_variable_instance_editable(bp, var[0], True)
    for name, cls, container in spec.get("object_variables", ()):
        if name not in have:
            bt.add_object_variable(bp, name, unreal.load_class(None, cls), None,
                                   getattr(_container(), container) if container else None)
        if spec.get("editable"):
            bt.set_variable_instance_editable(bp, name, True)
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
                if ptype in ("int", "float", "bool", "string", "name", "Vector", "Rotator", "Transform"):
                    bt.add_function_param(graph, pname, ptype, False, None)
                else:
                    bt.add_object_function_param(graph, pname, unreal.load_class(None, ptype), False, None)
    _components(bp, spec.get("components", ()))
    return graphs


def _components(bp, components) -> None:
    """Components the Blueprint's graphs use as variables, added under its root."""
    if not components:
        return
    sds = unreal.get_engine_subsystem(unreal.SubobjectDataSubsystem)
    handles = sds.k2_gather_subobject_data_for_blueprint(bp)
    lib = unreal.SubobjectDataBlueprintFunctionLibrary
    have = {str(lib.get_variable_name(lib.get_data(h))) for h in handles}
    for name, cls in components:
        if name in have:
            continue
        params = unreal.AddNewSubobjectParams(parent_handle=handles[0], new_class=getattr(unreal, cls).static_class(),
                                              blueprint_context=bp)
        handle, failure = sds.add_new_subobject(params)
        if not lib.is_handle_valid(handle):
            raise RuntimeError(f"could not add the component {name} to {bp.get_name()}: {failure}")
        sds.rename_subobject(handle, unreal.Text(name))


def _write(bt, bp, spec: dict, graphs: dict) -> None:
    """Function bodies and events (a write replaces the forms it names),
    compiled, defaults set, verified."""
    for fname, _, _, dsl in spec.get("functions", ()):
        bt.write_graph_dsl(graphs[fname], dsl)
    if spec.get("events"):
        bt.write_graph_dsl(unreal.BlueprintEditorLibrary.find_event_graph(bp), spec["events"])
    bt.compile_blueprint(bp, False)
    if spec.get("defaults"):
        cdo = unreal.get_default_object(_class(spec["name"]))
        for key, value in spec["defaults"].items():
            cdo.set_editor_property(key, value)
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
    unreal.EditorAssetLibrary.set_metadata_tag(asset, VERSION_TAG, _build_id(name))
    unreal.EditorAssetLibrary.save_loaded_asset(asset, False)


SHOOTER_NAMES = [s["name"] for s in shooter_spec.specs({})]


def _info_spec() -> dict:
    """The level's game info: the template game's fields and the shooter's."""
    spec = dict(game_spec.GAME_INFO)
    spec["variables"] = list(spec["variables"]) + shooter_spec.INFO_VARIABLES
    spec["object_variables"] = list(spec["object_variables"]) + shooter_spec.INFO_OBJECTS
    spec["defaults"] = {**spec["defaults"], **shooter_spec.INFO_DEFAULTS}
    return spec


def _build_shooter(bt) -> None:
    """The shooter's four Blueprints: declared together first (they call one
    another), then written, compiled and given their defaults."""
    # The game info carries the shooter's fields: add any this build has new,
    # and save it (a fresh editor would load it without them and every shooter
    # Blueprint would fail to compile).
    info = _blueprint(bt, game_spec.GAME_INFO["name"], unreal.Actor.static_class())
    _apply(bt, info, _info_spec())
    unreal.EditorAssetLibrary.save_loaded_asset(info, False)
    assets = game_assets.ensure()
    specs = shooter_spec.specs(assets)
    made = []
    for spec in specs:
        parent = spec["parent"]
        cls = unreal.load_class(None, parent) if parent.startswith("/Script/") else \
            unreal.load_class(None, parent) or unreal.EditorAssetLibrary.load_blueprint_class(parent.rsplit(".", 1)[0])
        if cls is None:
            raise RuntimeError(f"no parent class {parent} for {spec['name']}")
        bp = _blueprint(bt, spec["name"], cls)
        made.append((bp, spec, _declare(bt, bp, spec)))
    for bp, _, _ in made:
        bt.compile_blueprint(bp, False)
    for bp, spec, graphs in made:
        _write(bt, bp, spec, graphs)
    bot = unreal.get_default_object(_class("BP_MixarBot"))
    bot.set_editor_property("auto_possess_ai", unreal.AutoPossessAI.PLACED_IN_WORLD_OR_SPAWNED)
    bot.set_editor_property("ai_controller_class", unreal.AIController.static_class())
    gm = unreal.get_default_object(_class("BP_MixarShooterGameMode"))
    gm.set_editor_property("default_pawn_class", _class("BP_MixarShooterPlayer"))
    gm.set_editor_property("hud_class", _class("BP_MixarShooterHUD"))
    gm.set_editor_property("Template", game_spec.TEMPLATES["shooter"])
    for bp, _, _ in made:
        bt.compile_blueprint(bp, False)


def ensure(template: str = "") -> dict:
    """{template: GameMode class path} for every template, or {"error"}."""
    names = [game_spec.GAME_INFO["name"], game_spec.GAME_MODE["name"], game_spec.HUD["name"], *CHILDREN.values()]
    base_ok = all(_current(n) for n in names)
    shooter = template == "shooter" and not all(_current(n) for n in SHOOTER_NAMES)
    if base_ok and not shooter:
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
        if not base_ok:
            _build_base(bt, parent, names)
        if shooter:
            _build_shooter(bt)
            for name in SHOOTER_NAMES:
                _stamp(name)
    except Exception as exc:  # noqa: BLE001 - a build that fails says why
        for name in SHOOTER_NAMES if shooter else names:  # never current until a build succeeds
            asset = unreal.EditorAssetLibrary.load_asset(_path(name)) \
                if unreal.EditorAssetLibrary.does_asset_exist(_path(name)) else None
            if asset is not None:
                unreal.EditorAssetLibrary.set_metadata_tag(asset, VERSION_TAG, "failed")
        return {"error": f"Building the template game failed: {exc}"}
    return _classes()


def _build_base(bt, parent, names) -> None:
    """The template game: game info, sounds and effects, GameMode, HUD, children."""
    info = _blueprint(bt, game_spec.GAME_INFO["name"], unreal.Actor.static_class())
    _apply(bt, info, _info_spec())
    assets = game_assets.ensure()
    spec = dict(game_spec.GAME_MODE)
    spec["functions"] = list(spec["functions"]) + game_spec.fx_functions(assets)
    gm = _blueprint(bt, game_spec.GAME_MODE["name"], parent)
    _apply(bt, gm, spec)
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
    for name in names:
        _stamp(name)


def _classes() -> dict:
    out = {"third_person": _class(game_spec.GAME_MODE["name"]), **{t: _class(n) for t, n in CHILDREN.items()}}
    shooter = _class("BP_MixarShooterGameMode")
    if shooter is not None:
        out["shooter"] = shooter
    return out


def info_class():
    return _class(game_spec.GAME_INFO["name"])


def game_mode(world):
    """The running game's Mixar GameMode (a BP_MixarGameMode), or None."""
    gm = unreal.GameplayStatics.get_game_mode(world) if world else None
    base = _class(game_spec.GAME_MODE["name"])
    if gm is None or base is None or not unreal.MathLibrary.class_is_child_of(gm.get_class(), base):
        return None
    return gm
