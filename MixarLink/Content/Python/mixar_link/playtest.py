"""Playtests: scripted steps in the running game, the game state after each.

The same steps as Mixar Link for Godot: ``hold`` / ``press`` an input action,
``wait``, ``walk_to`` a Blender-frame point, ``prove_loop`` (every pickup,
nearest first, then the goal), ``inspect`` an actor's live values (its own or
a component's: ``LightComponent.Intensity``), ``state``.
They run in a level made with a template: its GameMode
(``BP_MixarGameMode``) holds the state and injects input through Enhanced
Input (``MixarInject``), so the game sees the same actions a player's keys
make. ``walk_to`` steers the player with movement input along a path over the
level's navigation mesh (``MixarNavigation``, rebuilt as doors open), jumps
once when blocked, and reports reached / stuck / timed_out / no_path. A path
that ends short is asked for again for a few seconds before ``no_path`` (a
moving hazard or an opening door changes the navigation mesh for a moment),
and a death mid-walk routes again from the respawn point.

A step that fails is reported and the next one still runs; only a game that
stopped or lost its player ends the run. The result says how the game stood
when the run began (``fresh_start``): a win counts as a clean proof only from
a fresh start by ``prove_loop`` (``proof``).

A run is a generator advanced once per editor tick (``play.wait``), so the
game keeps running between steps.
"""

import json
import math
import time

import unreal

from . import frames, game, nodes, play

REACHED_M = 0.6
WAYPOINT_M = 0.5
STALL_S = 1.5
NO_PATH_RETRY_S = 3.0
RUN_TIMEOUT_S = 290.0
# Godot's action names on the third-person template's Enhanced Input actions
# (IA_Move is X right / Y forward; IA_Look X turns the camera).
ACTIONS = {
    "move_forward": ("IA_Move", (0.0, 1.0, 0.0)),
    "move_back": ("IA_Move", (0.0, -1.0, 0.0)),
    "move_left": ("IA_Move", (-1.0, 0.0, 0.0)),
    "move_right": ("IA_Move", (1.0, 0.0, 0.0)),
    "jump": ("IA_Jump", (1.0, 0.0, 0.0)),
    "camera_left": ("IA_Look", (-1.0, 0.0, 0.0)),
    "camera_right": ("IA_Look", (1.0, 0.0, 0.0)),
}


def _input_actions() -> dict:
    """The project's InputAction assets by name."""
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    found = {}
    for data in registry.get_assets_by_class(unreal.TopLevelAssetPath("/Script/EnhancedInput", "InputAction")):
        path = str(data.package_name)
        if path.startswith("/Game/"):
            found.setdefault(str(data.asset_name), path)
    return found


def _action_names(assets: dict) -> list:
    return sorted(set(ACTIONS) | set(assets))


def _resolve(name: str, assets: dict):
    """(InputAction, value vector) for an action name, or None."""
    asset_name, value = ACTIONS.get(name, (name, (1.0, 0.0, 0.0)))
    path = assets.get(asset_name)
    action = unreal.load_asset(path) if path else None
    return (action, unreal.Vector(*value)) if action else None


def _sleep(seconds: float):
    end = time.time() + seconds
    while time.time() < end:
        yield


def _player(world):
    return unreal.GameplayStatics.get_player_character(world, 0)


def _flat(a, b) -> float:
    """Horizontal distance in metres between two Unreal points."""
    return math.hypot(a.x - b.x, a.y - b.y) / 100.0


def _center(actor):
    origin, _ = actor.get_actor_bounds(False)
    return origin


def run(steps_json: str):
    try:
        steps = json.loads(steps_json or "[]")
    except ValueError as exc:
        return play.done(play._err(f"steps is not JSON: {exc}"))
    if not isinstance(steps, list) or not steps:
        return play.done(play._err("steps must be a non-empty list."))
    world = play.game_world()
    if world is None:
        return play.done(play._err("The game is not running; call play first."))
    gm = game.game_mode(world)
    if gm is None:
        return play.done(play._err(
            "Playtests need a level made with a template (new_scene with template=third_person, "
            "top_down or platformer): its GameMode keeps the game state and takes the input."))
    runner = _Run(world, gm)
    gen = runner.steps(steps)

    def advance():
        if play.game_world() is None:
            return play._err("The game stopped during the playtest.", steps=runner.results)
        try:
            next(gen)
        except StopIteration as stop:
            return play._ok(stop.value)
        return None

    return play.wait(advance, RUN_TIMEOUT_S, lambda: play._err("The playtest ran out of time.",
                                                               steps=runner.results))


class _Run:
    """One playtest's state. (A plain class: nothing here is a UObject.)"""

    def __init__(self, world, gm):
        self.world = world
        self.gm = gm
        self.assets = _input_actions()
        self.results = []

    # -- steps --------------------------------------------------------------

    def steps(self, steps):
        start = self.state()
        for step in steps:
            if not isinstance(step, dict):
                result = {"error": "a step must be an object"}
            elif "hold" in step:
                result = yield from self.hold(str(step["hold"]), _clamp(step.get("seconds", 0.5), 0.0, 30.0))
            elif "press" in step:
                result = yield from self.hold(str(step["press"]), 0.0)
            elif "wait" in step:
                yield from _sleep(_clamp(step["wait"], 0.0, 30.0))
                result = {}
            elif "walk_to" in step:
                target = frames.from_blender(step["walk_to"])
                result = yield from self.walk_to(unreal.Vector(*target), _clamp(step.get("timeout", 15.0), 1.0, 60.0))
            elif "prove_loop" in step:
                result = yield from self.prove_loop(_clamp(step.get("timeout", 15.0), 1.0, 60.0))
            elif "fire" in step:
                result = yield from self.fire(_clamp(step.get("fire") if not isinstance(step.get("fire"), bool)
                                                     else 0.1, 0.05, 10.0))
            elif "reload" in step:
                result = self.flag("ReloadHeld")
            elif "god" in step:
                result = self.flag("God", bool(step["god"]))
            elif "aim_at" in step:
                result = self.aim_at(step["aim_at"])
            elif "inspect" in step:
                result = self.inspect(step["inspect"])
            elif "state" in step:
                result = {}
            else:
                result = {"error": "unknown step; use hold, press, wait, walk_to, prove_loop, inspect, state "
                                   "(shooter: fire, reload, aim_at)"}
            result["step"] = step
            result["state"] = self.state()
            self.results.append(result)
            if result.get("fatal"):
                break
        out = {"steps": self.results, "final_state": self.state(), "start_state": start,
               "fresh_start": not start.get("collected") and not start.get("deaths") and not start.get("won"),
               "errors": sum(1 for r in self.results if "error" in r)}
        out["proof"] = _proof(out)
        return out

    def hold(self, name: str, seconds: float):
        resolved = _resolve(name, self.assets)
        if resolved is None:
            return {"error": f"no input action '{name}' (actions: {', '.join(_action_names(self.assets))})"}
        action, value = resolved
        end = time.time() + seconds
        frames_left = 2  # a tap is held for two frames
        while frames_left > 0 or time.time() < end:
            self.gm.call_method("MixarInject", (action, value))
            frames_left -= 1
            yield
        yield
        return {}

    def _route(self, player, target):
        """(route, routed) to ``target`` over the navigation mesh, or None when
        no path reaches it for NO_PATH_RETRY_S. No mesh at all: straight."""
        deadline = time.time() + NO_PATH_RETRY_S
        while True:
            path = unreal.NavigationSystemV1.find_path_to_location_synchronously(
                self.world, player.get_actor_location(), target)
            points = list(path.path_points) if path else []
            if not points:
                return [target], False
            if _flat(points[-1], target) <= 1.0:
                return points[1:] + [target], True
            if time.time() > deadline:  # the path still ends short: nothing connects
                return None
            yield

    def walk_to(self, target, timeout: float):
        player = _player(self.world)
        if player is None:
            return {"error": "the game has no player character", "fatal": True}
        found = yield from self._route(player, target)
        if found is None:
            return {"reached": False, "no_path": True,
                    "distance_m": round(_flat(player.get_actor_location(), target), 2), "seconds": 0.0}
        route, routed = found
        t0 = time.time()
        best, best_at, jumped, leg = float("inf"), t0, False, 0
        deaths_at_start = self._deaths()
        seen_deaths = deaths_at_start
        result = {}
        while True:
            yield
            if not unreal.SystemLibrary.is_valid(player):
                return {"error": "the player was removed", "fatal": True}
            deaths = self._deaths()
            if deaths > seen_deaths:  # killed and respawned: the walk starts over from there
                seen_deaths = deaths
                found = yield from self._route(player, target)
                if found is None:
                    result = {"reached": False, "no_path": True}
                    break
                route, routed = found
                best, best_at, jumped, leg = float("inf"), time.time(), False, 0
            here = player.get_actor_location()
            left = _flat(here, target)
            if left < REACHED_M:
                result = {"reached": True}
                break
            if leg < len(route) - 1 and _flat(here, route[leg]) < WAYPOINT_M:
                leg += 1
            aim = route[leg]
            direction = unreal.Vector(aim.x - here.x, aim.y - here.y, 0.0)
            length = math.hypot(direction.x, direction.y)
            if length > 0:
                player.add_movement_input(unreal.Vector(direction.x / length, direction.y / length, 0.0), 1.0)
            now = time.time()
            if left < best - 0.05:
                best, best_at = left, now
            elif now - best_at > STALL_S:
                if not jumped:
                    player.jump()
                    jumped, best_at = True, now
                else:
                    result = {"reached": False, "stuck": True}
                    break
            if now - t0 > timeout:
                result = {"reached": False, "timed_out": True}
                break
        result["distance_m"] = round(_flat(player.get_actor_location(), target), 2)
        result["seconds"] = round(time.time() - t0, 1)
        result["routed"] = routed
        if seen_deaths > deaths_at_start:
            result["died"] = seen_deaths - deaths_at_start
        return result

    # -- shooter --------------------------------------------------------------

    def _shooter(self):
        player = _player(self.world)
        if player is None or not _has(player, "FireHeld"):
            return None
        return player

    def fire(self, seconds: float):
        """Hold the trigger (the shooter player's FireHeld) for ``seconds``."""
        player = self._shooter()
        if player is None:
            return {"error": "fire needs a shooter level (new_scene template=shooter)"}
        before, clock = player.get_editor_property("Ammo"), player.get_editor_property("Clock")
        player.set_editor_property("FireHeld", True)
        yield from _sleep(seconds)
        if not unreal.SystemLibrary.is_valid(player):
            return {"shots": 0}
        player.set_editor_property("FireHeld", False)
        # game time the trigger was down (a slow editor frame makes it longer than asked)
        held = player.get_editor_property("Clock") - clock
        yield
        return {"shots": before - player.get_editor_property("Ammo"), "game_seconds": round(held, 2)}

    def flag(self, name: str, value: bool = True) -> dict:
        player = self._shooter()
        if player is None:
            return {"error": f"{name} needs a shooter level (new_scene template=shooter)"}
        player.set_editor_property(name, value)
        return {}

    def aim_at(self, point) -> dict:
        """Turn the view to a Blender-frame point."""
        try:
            target = unreal.Vector(*frames.from_blender(point))
        except Exception:  # noqa: BLE001
            return {"error": "aim_at takes [x, y, z] (Blender frame)"}
        camera = unreal.GameplayStatics.get_player_camera_manager(self.world, 0)
        controller = unreal.GameplayStatics.get_player_controller(self.world, 0)
        if camera is None or controller is None:
            return {"error": "the game has no player view"}
        look = unreal.MathLibrary.find_look_at_rotation(camera.get_camera_location(), target)
        controller.set_control_rotation(look)
        return {"pitch": round(look.pitch, 1), "yaw": round(look.yaw, 1)}

    def _deaths(self) -> int:
        try:
            return int(self.gm.get_editor_property("Deaths"))
        except Exception:  # noqa: BLE001 - a game mode without the counter
            return 0

    def prove_loop(self, timeout_each: float):
        """Every pickup (nearest first, a second try for any missed once the
        rest are in), then the goal."""
        player = _player(self.world)
        if player is None:
            return {"error": "the game has no player character", "fatal": True}
        t0, deaths0 = time.time(), self._deaths()
        visits, unreached = [], []
        pickups = list(unreal.GameplayStatics.get_all_actors_with_tag(self.world, "mixar_role=pickup"))
        for attempt in (1, 2):
            missed = []
            remaining = list(pickups)
            while True:
                remaining = [a for a in remaining if unreal.SystemLibrary.is_valid(a)
                             and a.get_actor_label() not in missed]
                if not remaining:
                    break
                here = player.get_actor_location()
                remaining.sort(key=lambda a: _flat(here, _center(a)))
                target = remaining[0]
                name = target.get_actor_label()
                visit = yield from self.walk_to(_center(target), timeout_each)
                visit["target"] = name
                visit["collected"] = not unreal.SystemLibrary.is_valid(target)
                if attempt == 2:
                    visit["retry"] = True
                visits.append(visit)
                if not visit["collected"]:
                    missed.append(name)
            unreached = missed
            if not missed:
                break
        goals = list(unreal.GameplayStatics.get_all_actors_with_tag(self.world, "mixar_role=goal"))
        if not goals:
            return {"visits": visits, "unreached": unreached, "error": "the level has no goal (mixar_role goal)"}
        yield from _sleep(1.5)  # the doors finish opening
        goal = goals[0]
        visit = yield from self.walk_to(_center(goal), timeout_each)
        visit["target"] = goal.get_actor_label()
        visits.append(visit)
        if not visit.get("reached"):
            unreached.append(goal.get_actor_label())
        yield from _sleep(0.2)
        won = bool(self.state().get("won"))
        return {"visits": visits, "unreached": unreached, "won": won, "deaths": self._deaths() - deaths0,
                "seconds": round(time.time() - t0, 1), "clean": won and not unreached}

    def inspect(self, spec) -> dict:
        if not isinstance(spec, dict) or not spec.get("node"):
            return {"error": "inspect needs {node, properties}"}
        name = str(spec["node"])
        actors = list(unreal.GameplayStatics.get_all_actors_of_class(self.world, unreal.Actor))
        actor = next((a for a in actors if name in (a.get_actor_label(), _path(a), a.get_name())), None)
        if actor is None:
            # spawned actors have runtime names: name the ones of a matching class
            like = [a.get_name() for a in actors if name.lower().rstrip("_0123456789") in
                    a.get_class().get_name().lower()][:20]
            return {"error": f"no actor '{name}' in the running game", "similar": like}
        values, blender = {}, []
        for key in spec.get("properties") or ["position"]:
            key = str(key)
            try:
                value, in_blender = _read(actor, key)
            except Exception:  # noqa: BLE001 - an unknown property is a value, not a failure
                values[key] = "<no such property>"
                continue
            values[key] = value
            if in_blender:
                blender.append(key)
        return {"node": _path(actor), "type": actor.get_class().get_name(), "values": values,
                "blender_frame": blender}

    def state(self) -> dict:
        gm, out = self.gm, {}
        if unreal.SystemLibrary.is_valid(gm):
            for key, prop in (("collected", "Collected"), ("total", "Total"), ("won", "Won"), ("lost", "Lost"),
                              ("deaths", "Deaths"), ("doors_open", "DoorsOpen")):
                out[key] = gm.get_editor_property(prop)
            reported = gm.get_editor_property("State")
            for key in reported:
                out[str(key)] = _number(str(reported[key]))
        player = _player(self.world)
        if player is not None:
            out["player_position"] = frames.to_blender(player.get_actor_location())
            out["on_floor"] = bool(player.character_movement.is_moving_on_ground())
        return out


def _proof(out: dict) -> str:
    """How far the run proves the game winnable: ``prove_loop`` from a fresh
    start, a win by other steps (hand-picked routes) or none."""
    if not out["final_state"].get("won"):
        return "not_won"
    loops = [r for r in out["steps"] if "prove_loop" in (r.get("step") or {})]
    if out["fresh_start"] and any(r.get("won") for r in loops):
        return "prove_loop_fresh"
    return "won_by_steps" if out["fresh_start"] else "won_not_fresh"


def _has(obj, name: str) -> bool:
    try:
        obj.get_editor_property(name)
    except Exception:  # noqa: BLE001
        return False
    return True


def _clamp(value, lo: float, hi: float) -> float:
    try:
        return max(lo, min(float(value), hi))
    except (TypeError, ValueError):
        return lo


def _number(text: str):
    """A reported value as a number when it reads as one."""
    try:
        return int(text)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return {"true": True, "false": False}.get(text.lower(), text)


def _path(actor) -> str:
    folder = str(actor.get_folder_path() or "")
    label = actor.get_actor_label()
    return f"{folder}/{label}" if folder and folder != "None" else label


def _read(actor, key: str):
    """(value, in the Blender frame?) of an actor's live property."""
    if key in ("position", "location", "global_position"):
        return frames.to_blender(actor.get_actor_location()), True
    if key == "velocity":
        v = actor.get_velocity()
        return [round(v.x / 100.0, 3), round(-v.y / 100.0, 3), round(v.z / 100.0, 3)], True
    if key == "rotation":
        r = actor.get_actor_rotation()
        return [round(r.roll, 2), round(r.pitch, 2), round(r.yaw, 2)], False
    if key == "hidden":
        return bool(actor.get_editor_property("hidden")), False
    if key == "bounds":  # the rendered size in metres (a pose gone wrong shows here)
        _, extent = actor.get_actor_bounds(False)
        return [round(extent.x / 50.0, 2), round(extent.y / 50.0, 2), round(extent.z / 50.0, 2)], False
    obj, name = nodes._target(actor, key)  # Component.Property, or a component's own
    return _plain(obj.get_editor_property(name)), False


def _plain(value):
    if isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, unreal.Vector):
        return [round(value.x, 3), round(value.y, 3), round(value.z, 3)]
    if isinstance(value, unreal.Rotator):
        return [round(value.roll, 2), round(value.pitch, 2), round(value.yaw, 2)]
    if isinstance(value, unreal.Object):
        return value.get_path_name()
    return str(value)[:200]
