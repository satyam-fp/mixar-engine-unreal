"""Actors in the open level: ``add_node`` and ``set_property``.

``add_node`` spawns an actor of a built-in class (``PointLight``,
``TriggerBox``, ``/Script/Engine.TextRenderActor`` …) or of a Blueprint the
agent made under /Game/Mixar. ``set_property`` sets one property of an actor
or of one of its components (``Component.Property``). ``position`` and
``yaw_deg`` are Blender's frame, like ``place``; every other value is
Unreal's own (centimetres, degrees, Z up): a list becomes the property's
vector, rotator ([roll, pitch, yaw], the Details panel's X Y Z) or colour; an
asset or class path loads it; an enum takes its name. Both are undoable and
save the level, and both refuse levels outside /Game/Mixar in plugin mode.
"""

import json

import unreal

from . import MIXAR_FOLDER, frames, level


def _sub(cls):
    return unreal.get_editor_subsystem(cls)


def actor_class(name: str):
    """A spawnable Actor class from a short name, a /Script path or a
    Blueprint asset path; None when it is not one."""
    cls = None
    if name.startswith("/Game/"):
        cls = unreal.EditorAssetLibrary.load_blueprint_class(name.split(".", 1)[0])
    elif name.startswith("/Script/"):
        cls = unreal.load_class(None, name)
    else:
        py = getattr(unreal, name, None)
        cls = py.static_class() if isinstance(py, type) and hasattr(py, "static_class") else None
    if cls is None or not unreal.MathLibrary.class_is_child_of(cls, unreal.Actor.static_class()):
        return None
    return cls


def find(node: str):
    for actor in _sub(unreal.EditorActorSubsystem).get_all_level_actors():
        if level._outliner_path(actor) == node or actor.get_actor_label() == node:
            return actor
    return None


def add_node(type_name: str, name: str, parent: str, position) -> dict:
    reason = level.refusal()
    if reason:
        return {"error": reason}
    cls = actor_class(type_name)
    if cls is None:
        return {"error": f"'{type_name}' is not an actor class (a built-in one such as PointLight, "
                         f"TriggerBox, TextRenderActor, or a Blueprint under {MIXAR_FOLDER})."}
    if not name or not all(c.isalnum() or c in "_-" for c in name):
        return {"error": "name must be letters, digits, _ and -."}
    parent_actor = find(parent) if parent else None
    if parent and parent_actor is None:
        return {"error": f"No actor at {parent} (paths come from scene_tree)."}
    at = frames.from_blender(position) if position else (0.0, 0.0, 0.0)
    with unreal.ScopedEditorTransaction(f"Mixar: add {name}"):
        actor = _sub(unreal.EditorActorSubsystem).spawn_actor_from_class(cls, unreal.Vector(*at))
        if actor is None:
            return {"error": f"Unreal could not spawn a {type_name}."}
        actor.set_actor_label(level._unique(name))
        if parent_actor:
            actor.attach_to_actor(parent_actor, "", unreal.AttachmentRule.KEEP_WORLD,
                                  unreal.AttachmentRule.KEEP_WORLD, unreal.AttachmentRule.KEEP_WORLD, False)
    level.save()
    return {"node": level._outliner_path(actor), "type": cls.get_name(), "scene": level.level_path()}


def _target(actor, prop: str):
    """(object, property name): ``Component.Property`` reaches a component."""
    if "." not in prop:
        return actor, prop
    comp_name, prop = prop.split(".", 1)
    for comp in actor.get_components_by_class(unreal.ActorComponent):
        if comp.get_name() == comp_name:
            return comp, prop
    raise LookupError(f"{actor.get_actor_label()} has no component {comp_name} "
                      f"(it has: {', '.join(c.get_name() for c in actor.get_components_by_class(unreal.ActorComponent))})")


def _convert(current, value):
    """``value`` (JSON) as the type ``current`` has."""
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, (int, float)) and not isinstance(value, (list, dict)):
        return type(current)(value)
    if isinstance(current, unreal.Vector):
        return unreal.Vector(*[float(v) for v in value])
    if isinstance(current, unreal.Rotator):
        roll, pitch, yaw = [float(v) for v in value]
        return unreal.Rotator(roll=roll, pitch=pitch, yaw=yaw)
    if isinstance(current, unreal.LinearColor):
        return unreal.LinearColor(*[float(v) for v in (list(value) + [1.0])[:4]])
    if isinstance(current, unreal.Color):
        return unreal.Color(*[int(v) for v in (list(value) + [255])[:4]])
    if isinstance(current, unreal.Name):
        return unreal.Name(str(value))
    if isinstance(current, unreal.Text):
        return unreal.Text(str(value))
    if isinstance(current, unreal.EnumBase):
        return getattr(type(current), str(value).upper())
    if isinstance(value, str) and value.startswith(("/Game/", "/Script/", "/Engine/")):
        loaded = unreal.load_class(None, value) if value.startswith("/Script/") or value.endswith("_C") \
            else unreal.load_asset(value)
        if loaded is None and value.startswith("/Game/"):
            loaded = unreal.EditorAssetLibrary.load_blueprint_class(value)
        if loaded is None:
            raise ValueError(f"nothing at {value}")
        return loaded
    if isinstance(current, unreal.Array) and isinstance(value, list):
        return value
    return value


def set_property(node: str, prop: str, value_json: str) -> dict:
    reason = level.refusal()
    if reason:
        return {"error": reason}
    actor = find(node)
    if actor is None:
        return {"error": f"No actor at {node} (paths come from scene_tree)."}
    try:
        value = json.loads(value_json) if value_json else None
    except ValueError:
        value = value_json
    with unreal.ScopedEditorTransaction(f"Mixar: set {node} {prop}"):
        actor.modify()
        try:
            if prop == "position":
                actor.set_actor_location(unreal.Vector(*frames.from_blender(value)), False, True)
            elif prop == "yaw_deg":
                r = actor.get_actor_rotation()
                actor.set_actor_rotation(unreal.Rotator(roll=r.roll, pitch=r.pitch,
                                                        yaw=frames.yaw_from_blender(float(value))), True)
            elif prop == "scale":
                actor.set_actor_scale3d(unreal.Vector(*([float(value)] * 3 if not isinstance(value, list)
                                                       else [float(v) for v in value])))
            elif prop == "label":
                actor.set_actor_label(str(value))
            elif prop == "hidden":
                actor.set_actor_hidden_in_game(bool(value))
            elif prop == "tags":
                actor.tags = [unreal.Name(str(t)) for t in value or []]
            else:
                obj, name = _target(actor, prop)
                current = obj.get_editor_property(name)
                obj.set_editor_property(name, _convert(current, value))
        except Exception as exc:  # noqa: BLE001 - the reason goes back to the agent
            return {"error": f"Could not set {prop} on {node}: {exc}"}
    level.save()
    return {"node": level._outliner_path(actor), "property": prop, "scene": level.level_path()}
