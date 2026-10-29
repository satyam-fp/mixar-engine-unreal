"""The ``blueprint`` tool: the agent's way to write game logic in Unreal.

A thin, path-guarded front for Epic's EditorToolset ``BlueprintTools``: make
a Blueprint, read or write its graphs in Epic's S-expression graph DSL, add
variables and function parameters, look node types and their pins up,
compile. Writing an ``(event …)`` or ``(fn …)`` form replaces that event's or
function's graph and leaves the rest; a write compiles, and compile errors
come back.

Blueprints are written only under /Game/Mixar (in every project mode), never
in /Game/Mixar/Game (the template game, which Mixar Link rebuilds); any
Blueprint can be read.
"""

import unreal

from . import MIXAR_FOLDER, game

BLUEPRINTS = f"{MIXAR_FOLDER}/Blueprints"
NOTES = """
MIXAR NOTES
- Blueprints you write live under /Game/Mixar (default /Game/Mixar/Blueprints).
- The template game's GameMode is BP_MixarGameMode (/Game/Mixar/Game). Tell it what
  happened from any Blueprint:
    (bind gm (Utilities|Casting|CastToBP_MixarGameMode :Object (Game|GetGameMode))
      (:then (Class|BPMixarGameMode|OnMixarEvent :self gm :Event "hazard" :Source self))
      (:CastFailed))
  Events: pickup, hazard, checkpoint, goal, lose, restart. Report your own values to
  playtests with (Class|BPMixarGameMode|ReportState :self gm :Key "time_left" :Value ...).
- Actors placed from Mixar packages carry tags such as mixar_role=pickup;
  (Actor|GetAllActorswithTag :Tag "mixar_role=door") finds them.
- Units are centimetres, Z up; Blender (x, y, z) m is Unreal (100x, -100y, 100z) cm.
- Never guess a node type id or pin name: find_nodes, then node_pins.
"""

# Parent classes by short name (anything else: a /Script path or a Blueprint path).
PARENTS = ("Actor", "Pawn", "Character", "ActorComponent", "SceneComponent", "GameModeBase", "HUD",
           "PlayerController", "GameStateBase", "PlayerState")


def _bt():
    return game.tools()


def _parent(name: str):
    if name in PARENTS:
        return getattr(unreal, name).static_class()
    if name.startswith("/Script/"):
        return unreal.load_class(None, name)
    if name.startswith("/Game/"):
        return unreal.EditorAssetLibrary.load_blueprint_class(name.split(".", 1)[0])
    return None


def _writable(path: str) -> str:
    if not path.startswith(MIXAR_FOLDER + "/"):
        return f"Blueprints are written under {MIXAR_FOLDER} only (e.g. {BLUEPRINTS}/BP_Name)."
    if path.startswith(game.GAME_FOLDER + "/"):
        return (f"{game.GAME_FOLDER} is the template game, rebuilt by Mixar Link; make your own "
                f"Blueprint (a child of BP_MixarGameMode works) under {BLUEPRINTS}.")
    return ""


def _load(path: str):
    # unreal.load_asset: EditorAssetLibrary refuses while the game runs.
    path = path.split(".", 1)[0]
    asset = unreal.load_asset(f"{path}.{path.rsplit('/', 1)[-1]}")
    return asset if isinstance(asset, unreal.Blueprint) else None


def _graph(bt, bp, name: str, create: bool = False):
    name = name or "EventGraph"
    for g in bt.list_graphs(bp):
        if g.get_name() == name:
            return g
    return bt.add_function_graph(bp, name) if create else None


def _container(type_name: str):
    from editor_toolset.toolsets.blueprint import ContainerType  # noqa: PLC0415
    if type_name.endswith("[]"):
        return type_name[:-2], ContainerType.ARRAY
    return type_name, None


def _summary(bt, bp) -> dict:
    return {"path": bp.get_path_name().split(".", 1)[0],
            "parent": str(bt.get_parent(bp).get_path_name()),
            "graphs": [g.get_name() for g in bt.list_graphs(bp)],
            "variables": list(bt.list_variables(bp))}


def blueprint(action: str, path: str, graph: str, code: str, name: str, type_name: str,
              parent: str, query: str, output: bool) -> dict:
    bt = _bt()
    if bt is None:
        return {"error": "Blueprint editing needs Unreal's EditorToolset plugin (Edit > Plugins > "
                         "EditorToolset, then restart the editor)."}
    if action == "docs":
        from editor_toolset.toolsets import blueprint_dsl  # noqa: PLC0415
        return {"docs": blueprint_dsl.USAGE + NOTES}
    path = (path or "").split(".", 1)[0]
    if action in ("create", "write", "add_variable", "add_param", "compile"):
        reason = _writable(path)
        if reason:
            return {"error": reason}
        if unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).is_in_play_in_editor():
            return {"error": "The game is running; stop it before changing Blueprints."}
    try:
        if action == "create":
            cls = _parent(parent or "Actor")
            if cls is None:
                return {"error": f"Unknown parent class {parent!r}: one of {', '.join(PARENTS)}, a /Script/ "
                                 f"class path or a Blueprint path."}
            if unreal.EditorAssetLibrary.does_asset_exist(path):
                return {"error": f"{path} exists; read it, or write into it."}
            folder, asset_name = path.rsplit("/", 1)
            bp = bt.create(folder, asset_name, cls)
            unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
            return _summary(bt, bp)
        bp = _load(path)
        if bp is None:
            return {"error": f"No Blueprint at {path}."}
        if action == "read":
            out = _summary(bt, bp)
            target = _graph(bt, bp, graph)
            if target is None:
                return {"error": f"{path} has no graph {graph!r}; graphs: {', '.join(out['graphs'])}"}
            out["graph"] = target.get_name()
            out["dsl"] = bt.read_graph_dsl(target)
            return out
        if action == "write":
            if not code:
                return {"error": "write needs code (graph DSL; action docs has the syntax)."}
            target = _graph(bt, bp, graph, create=True)
            bt.write_graph_dsl(target, code)
            unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
            return {**_summary(bt, bp), "graph": target.get_name(), "compiled": True}
        if action == "add_variable":
            base, container = _container(type_name)
            if base.startswith("/"):
                cls = unreal.load_class(None, base) if base.startswith("/Script/") else \
                    unreal.EditorAssetLibrary.load_blueprint_class(base)
                if cls is None:
                    return {"error": f"No class {base}."}
                bt.add_object_variable(bp, name, cls, None, container)
            else:
                bt.add_variable(bp, name, base, None, container)
            bt.compile_blueprint(bp, False)
            unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
            return _summary(bt, bp)
        if action == "add_param":
            target = _graph(bt, bp, graph, create=True)
            base, container = _container(type_name)
            if base.startswith("/"):
                cls = unreal.load_class(None, base) if base.startswith("/Script/") else \
                    unreal.EditorAssetLibrary.load_blueprint_class(base)
                bt.add_object_function_param(target, name, cls, not output, container)
            else:
                bt.add_function_param(target, name, base, not output, container)
            return {**_summary(bt, bp), "graph": target.get_name()}
        if action == "find_nodes":
            target = _graph(bt, bp, graph) or _graph(bt, bp, "EventGraph")
            return {"query": query, "type_ids": list(bt.find_node_types(target, query, []))[:60]}
        if action == "node_pins":
            target = _graph(bt, bp, graph) or _graph(bt, bp, "EventGraph")
            info = bt.get_node_type_pins(target, query)
            pins = lambda ps: [{"name": str(p.name), "type": str(p.type_id)} for p in ps]  # noqa: E731
            return {"type_id": query, "inputs": pins(info.input_pins), "outputs": pins(info.output_pins)}
        if action == "compile":
            bt.compile_blueprint(bp, False)
            unreal.EditorAssetLibrary.save_loaded_asset(bp, False)
            return {**_summary(bt, bp), "compiled": True}
    except Exception as exc:  # noqa: BLE001 - DSL and compile errors are the agent's to fix
        return {"error": str(exc)[:4000]}
    return {"error": "action must be docs, create, read, write, add_variable, add_param, find_nodes, "
                     "node_pins or compile."}
