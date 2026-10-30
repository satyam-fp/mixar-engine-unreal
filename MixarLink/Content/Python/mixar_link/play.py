"""Play In Editor and frames: ``play``, ``stop``, ``capture``.

These wait for something the editor does over several frames (the game
starting, a screenshot being written), so they answer asynchronously: the
tool returns a ``ToolCallAsyncResultString`` and a Slate post-tick callback
completes it once the condition holds or its time runs out. The editor keeps
running meanwhile.

``capture`` renders the running game's viewport (source ``game``) or the
level editor's viewport (``editor``) with ``HighResShot`` into a temporary
PNG, and returns it base64-encoded (``image_base64``, ``image_mime``).
"""

import base64
import json
import os
import tempfile
import time

import unreal

from . import level, logs

PLAY_TIMEOUT_S = 45.0
STOP_TIMEOUT_S = 10.0
CAPTURE_TIMEOUT_S = 20.0
# A started game counts once its player has a pawn and this long has passed,
# so its first frames are on screen.
WARMUP_S = 2.0


def _ok(data: dict) -> str:
    return json.dumps({"ok": True, "data": data})


def _err(message: str, **detail) -> str:
    return json.dumps({"ok": False, "error": message, **({"data": detail} if detail else {})})


def wait(check, timeout_s: float, on_timeout) -> "unreal.ToolCallAsyncResultString":
    """An async result completed with ``check()``'s first non-None value
    (checked every tick), or ``on_timeout()`` after ``timeout_s``."""
    result = unreal.ToolCallAsyncResultString()
    started = time.time()
    state = {"handle": None}

    def finish(text: str) -> None:
        if state["handle"] is not None:
            unreal.unregister_slate_post_tick_callback(state["handle"])
            state["handle"] = None
        result.set_value(text)

    def tick(_delta: float) -> None:
        try:
            value = check()
        except Exception as exc:  # noqa: BLE001 - the tool answers with the reason
            finish(_err(str(exc)))
            return
        if value is not None:
            finish(value)
        elif time.time() - started > timeout_s:
            finish(on_timeout())

    state["handle"] = unreal.register_slate_post_tick_callback(tick)
    return result


def done(text: str) -> "unreal.ToolCallAsyncResultString":
    result = unreal.ToolCallAsyncResultString()
    result.set_value(text)
    return result


def _les():
    return unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)


def game_world():
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_game_world()


def playing() -> bool:
    return bool(_les().is_in_play_in_editor())


def play(scene: str):
    which = scene or "main"
    target = level.main_level() if which == "main" else ("" if which == "current" else which.split(".", 1)[0])
    if which == "main" and not target:
        return done(_err("The project has no main level; new_scene(set_main=true), or play current."))
    if target and target != level.level_path():
        if playing():
            return done(_err("The game is running another level; stop it first."))
        opened = level.open_scene(target)
        if "error" in opened:
            return done(_err(opened["error"]))
    if not level.level_path():
        return done(_err("No level is open."))
    if not playing() and not level.refusal() and level.fit_navigation():
        level.save()
    since = logs.latest()
    scene_path = level.level_path()
    # A previous session first ends, then the new one is requested and awaited.
    state = {"phase": "stopping" if playing() else "request", "seen": 0.0}
    if state["phase"] == "stopping":
        _les().editor_request_end_play()

    def started():
        if state["phase"] == "stopping":
            if not playing():
                state["phase"] = "request"
            return None
        if state["phase"] == "request":
            state["phase"] = "starting"
            _les().editor_request_begin_play()
            return None
        world = game_world() if playing() else None
        if world is None or unreal.GameplayStatics.get_player_pawn(world, 0) is None:
            return None
        if not state["seen"]:
            state["seen"] = time.time()
        if time.time() - state["seen"] < WARMUP_S:
            return None
        return _ok({"playing": True, "game_connected": True, "scene": scene_path, "log_seq": since})

    def timed_out():
        return _err(f"The game did not start within {int(PLAY_TIMEOUT_S)} s; read log from log_seq.",
                    playing=playing(), log_seq=since, scene=scene_path)

    return wait(started, PLAY_TIMEOUT_S, timed_out)


def stop():
    if playing():
        _les().editor_request_end_play()
    return wait(lambda: None if playing() else _ok({"playing": False}), STOP_TIMEOUT_S,
                lambda: _err("The game did not stop.", playing=playing()))


def capture(source: str, max_width: int):
    width = max(256, min(int(max_width or 1280), 1920))
    height = int(round(width * 9 / 16 / 2) * 2)
    if source != "game":
        return _capture_editor()
    world = game_world()
    if world is None:
        return done(_err("The game is not running; call play first."))
    folder = tempfile.mkdtemp(prefix="mixar-capture-")
    path = os.path.join(folder, "frame.png")
    unreal.SystemLibrary.execute_console_command(world, f'HighResShot {width}x{height} filename="{path}"')
    state = {"size": -1}

    def written():
        if not os.path.isfile(path):
            return None
        size = os.path.getsize(path)
        if size <= 0 or size != state["size"]:  # still being written
            state["size"] = size
            return None
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
        try:
            os.remove(path)
            os.rmdir(folder)
        except OSError:
            pass
        return _ok({"source": source, "width": width, "height": height, "image_base64": data,
                    "image_mime": "image/png"})

    return wait(written, CAPTURE_TIMEOUT_S, lambda: _err("No frame was written in time; read log."))


# Epic's viewport capture renders the level editor's camera offscreen, so it
# works with the editor in the background (a HighResShot of a level viewport
# that is not realtime is never drawn).
EDITOR_CAPTURE = ("EditorToolset.EditorAppToolset", "CaptureViewport",
                  {"captureTransform": None, "annotations": None, "bShowUI": False})


def _capture_editor():
    toolset, tool, args = EDITOR_CAPTURE
    try:
        pending = unreal.ToolsetRegistry.execute_tool(toolset, tool, json.dumps(args))
    except Exception as exc:  # noqa: BLE001 - Epic's EditorToolset missing or changed
        return done(_err(f"The editor viewport cannot be captured here ({exc})."))

    def finished():
        if not pending.is_complete:
            return None
        if pending.error:
            return _err(f"The editor viewport capture failed: {pending.error}")
        value = json.loads(pending.get_value_as_json_string() or "{}")
        if isinstance(value, str):  # a JSON document inside the JSON string
            value = json.loads(value)
        if isinstance(value, dict) and isinstance(value.get("returnValue"), dict):
            value = value["returnValue"]
        image = value.get("image") if isinstance(value, dict) else None
        if not isinstance(image, dict) or not image.get("data"):
            return _err("The editor viewport capture returned no image.")
        width, height = image.get("width"), image.get("height")
        if not width:  # Epic's capture names no size; a PNG's header has it
            head = base64.b64decode(image["data"][:64])
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                width, height = int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
        return _ok({"source": "editor", "width": width, "height": height,
                    "image_base64": image["data"], "image_mime": image.get("mimeType") or "image/png"})

    return wait(finished, CAPTURE_TIMEOUT_S, lambda: _err("The editor viewport capture did not finish."))
