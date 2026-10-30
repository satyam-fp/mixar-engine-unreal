#!/usr/bin/env python3
"""End-to-end test of Mixar Link for Unreal against a real Unreal 5.8+ editor:
the plugin installed into a project, discovery, Unreal's MCP handshake, every
tool through ``call_tool``, and the discovery file removed on close.

    python3 test/run_e2e.py --project /path/to/Game.uproject [--editor /path/to/UnrealEditor] \
        [--packages DIR]

The project's Plugins/MixarLink is replaced with this checkout's, the plugins
Mixar Link needs are enabled in the .uproject, the MCP server is turned on
(port 9880) and the background throttle off in
Config/DefaultEditorPerProjectUserSettings.ini, and the project is marked
``owned`` (a game Mixar made). The project should have the third-person
template's Mannequin.

``--packages`` is a folder holding ``UEQA_PropYard`` and ``UEQA_Hero``, built
by ``test/make_packages.py`` with the Mixar desktop's own exporter. With it the
test also imports both, builds a level, places the 40 props (each at its
manifest origin, tagged) and the Tripo character looping a retargeted Mannequin
jog, plays, captures the game and the editor, reads the log, stops, checks the
plugin-mode refusals, and that nothing under Content/ outside Content/Mixar
changed. Exit code 0 = every check passed. The editor is opened and closed by
the test.
"""

from __future__ import annotations

import argparse
import base64
import glob
import json
import os
import shutil
import signal
import subprocess
import tempfile
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINK_DIR = os.path.join(os.path.expanduser("~"), ".mixar", "engine-link")
NEEDED_PLUGINS = ("ModelContextProtocol", "AllToolsets", "PythonScriptPlugin", "EditorScriptingUtilities",
                  "MixarLink")
SECTION = "[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]"
THROTTLE = "[/Script/UnrealEd.EditorPerformanceSettings]"
JOG = "/Game/Characters/Mannequins/Anims/Unarmed/Jog/MF_Unarmed_Jog_Fwd"
# new_scene's string arguments (the desktop fills these from the discovery file).
NEW_SCENE = {"template": "", "player_position": [], "look": "", "title": "", "objective": ""}
PORT = 9880

failures: list[str] = []


def check(name: str, ok: bool, detail: object = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    if not ok:
        failures.append(name)


def find_editor() -> str:
    pattern = {"darwin": "/Users/Shared/Epic Games/UE_5.*/Engine/Binaries/Mac/UnrealEditor.app/Contents/MacOS/UnrealEditor",
               "win32": r"C:\Program Files\Epic Games\UE_5.*\Engine\Binaries\Win64\UnrealEditor.exe"}
    found = sorted(glob.glob(pattern.get(sys.platform, "")))
    if not found:
        sys.exit("No UnrealEditor found; pass --editor.")
    return found[-1]


def install(uproject: str) -> None:
    project = os.path.dirname(uproject)
    target = os.path.join(project, "Plugins", "MixarLink")
    shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(os.path.join(ROOT, "MixarLink"), target, ignore=shutil.ignore_patterns("__pycache__"))
    with open(uproject, encoding="utf-8") as fh:
        desc = json.load(fh)
    plugins = desc.setdefault("Plugins", [])
    for name in NEEDED_PLUGINS:
        entry = next((p for p in plugins if p.get("Name") == name), None)
        if entry is None:
            plugins.append({"Name": name, "Enabled": True})
        else:
            entry["Enabled"] = True
    with open(uproject, "w", encoding="utf-8") as fh:
        json.dump(desc, fh, indent="\t")
    ini = os.path.join(project, "Config", "DefaultEditorPerProjectUserSettings.ini")
    text = open(ini, encoding="utf-8-sig").read() if os.path.exists(ini) else ""
    if SECTION not in text:
        text = text.rstrip("\n") + f"\n{SECTION}\nbAutoStartServer=True\nServerPortNumber={PORT}\n"
    if THROTTLE not in text:
        text = text.rstrip("\n") + f"\n{THROTTLE}\nbThrottleCPUWhenNotForeground=False\n"
    os.makedirs(os.path.dirname(ini), exist_ok=True)
    with open(ini, "w", encoding="utf-8") as fh:
        fh.write(text)
    set_mode(project, "owned")


def set_mode(project: str, mode: str) -> None:
    with open(os.path.join(project, "Config", "DefaultMixarLink.ini"), "w", encoding="utf-8") as fh:
        fh.write(f"[MixarLink]\nProjectMode={mode}\n")


def content_snapshot(project: str) -> dict:
    """Every file under Content/ outside Content/Mixar, with its mtime and size."""
    out = {}
    root = os.path.join(project, "Content")
    for folder, dirs, files in os.walk(root):
        if os.path.relpath(folder, root).split(os.sep)[0] == "Mixar":
            dirs[:] = []
            continue
        for name in files:
            path = os.path.join(folder, name)
            st = os.stat(path)
            out[os.path.relpath(path, root)] = (st.st_mtime, st.st_size)
    return out


class Mcp:
    def __init__(self, port: int, path: str):
        self.url = f"http://127.0.0.1:{port}/{path.lstrip('/')}"
        self.session = ""
        self.id = 0

    def post(self, payload: dict) -> tuple[int, dict, object]:
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.session:
            req.add_header("Mcp-Session-Id", self.session)
        with urllib.request.urlopen(req, timeout=2400) as resp:  # the shooter build takes minutes
            headers = {k.lower(): v for k, v in resp.headers.items()}
            text = resp.read().decode()
        if "text/event-stream" in headers.get("content-type", ""):
            data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            text = data[-1] if data else ""
        return resp.status, headers, json.loads(text) if text.strip() else None

    def rpc(self, method: str, params: dict) -> dict:
        self.id += 1
        _, headers, body = self.post({"jsonrpc": "2.0", "id": self.id, "method": method, "params": params})
        if method == "initialize":
            self.session = headers.get("mcp-session-id", "")
            self.post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return body

    def tool(self, toolset: str, name: str, arguments: dict) -> tuple[bool, dict, str]:
        """(server ok, the tool's parsed JSON reply, raw text)."""
        body = self.rpc("tools/call", {"name": "call_tool", "arguments": {
            "toolset_name": toolset, "tool_name": name, "arguments": arguments}})
        result = body.get("result") or {}
        text = (result.get("content") or [{}])[0].get("text", "")
        if result.get("isError"):
            return False, {}, text
        value = json.loads(text).get("returnValue")
        return True, json.loads(value) if isinstance(value, str) else value, text


def call(mcp, toolset, tool, arguments) -> tuple[bool, dict]:
    ok, reply, text = mcp.tool(toolset, tool, arguments)
    if not ok:
        return False, {"error": text}
    data = dict(reply.get("data") or {})
    if not reply.get("ok"):
        data["error"] = str(reply.get("error") or "")
    return bool(reply.get("ok")), data


def package_checks(mcp, toolset: str, packages: str, project: str) -> None:
    yard = os.path.join(packages, "UEQA_PropYard")
    manifest = json.load(open(os.path.join(yard, "manifest.json")))
    origins = {o["name"]: o["origin"] for o in manifest["engine"]["objects"]}
    ok, data = call(mcp, toolset, "import_package", {"source_dir": yard, "folder": "UEQA_PropYard"})
    check("import_package: 40 props", ok and len(data.get("objects") or []) == 40 and data.get("meshes") == 40, data)
    check("import_package: UCX hulls and mesh collision",
          data.get("collision") == {"convex_hulls": 25, "complex_as_simple": 5}, data.get("collision"))
    ok, data = call(mcp, toolset, "import_package", {"source_dir": yard, "folder": "../Escape"})
    check("import_package: a folder is a plain name", not ok, data)

    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2EYard", "player_position": [-13, 0, 1],
                                                "overwrite": True, "ground": True})
    check("new_scene", ok and data.get("scene") == "/Game/Mixar/Levels/E2EYard" and data.get("main"), data)
    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2EYard"})
    check("new_scene: an existing level needs overwrite", not ok, data)
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_PropYard", "name": "", "position": [0, 0, 0],
                                            "parent": "", "animation": ""})
    check("place: the package", ok and data.get("actors") == 40 and data.get("node") == "Mixar/UEQA_PropYard", data)
    ok, data = call(mcp, toolset, "scene_tree", {"max_nodes": 500})
    placed = {n["path"].rsplit("/", 1)[-1]: n for n in data.get("nodes") or []
              if n["path"].startswith("Mixar/UEQA_PropYard/")}
    off = [n for n, o in origins.items()
           if n not in placed or max(abs(a - b) for a, b in zip(placed[n]["position"], o)) > 0.01]
    check("place: every object at its manifest origin (Blender frame)", len(placed) == 40 and not off, off[:5])
    door = placed.get("Door_03", {}).get("tags") or []
    check("place: tags ride as actor tags", "mixar_role=door" in door and "mixar_pivot=hinge_z" in door, door)
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/ThirdPerson", "name": "", "position": [0, 0, 0],
                                            "parent": "", "animation": ""})
    check("place: only packages under /Game/Mixar", not ok, data)

    ok, data = call(mcp, toolset, "import_package", {"source_dir": os.path.join(packages, "UEQA_Hero"),
                                                     "folder": "UEQA_Hero"})
    chains = (data.get("retarget") or {}).get("chains") or []
    check("import_package: character with a Mannequin retargeter",
          ok and {"Spine", "Neck", "Head", "LeftLeg", "RightArm"} <= set(chains), data.get("retarget"))
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_Hero", "name": "Hero",
                                            "position": [-9.5, 1.0, 0], "yaw_deg": -90, "parent": "",
                                            "animation": JOG})
    check("place: the character loops a retargeted Mannequin clip",
          ok and data.get("animation") == "/Game/Mixar/UEQA_Hero/Anims/MF_Unarmed_Jog_Fwd_UEQA_Hero", data)

    ok, data = call(mcp, toolset, "play", {"scene": "main"})
    check("play", ok and data.get("playing") and data.get("scene") == "/Game/Mixar/Levels/E2EYard", data)
    since = data.get("log_seq", 0)
    ok, data = call(mcp, toolset, "capture", {"source": "game", "max_width": 640})
    png = base64.b64decode(data.get("image_base64") or "")
    check("capture: a game frame", ok and png[:8] == b"\x89PNG\r\n\x1a\n" and data.get("width") == 640, len(png))
    ok, data = call(mcp, toolset, "log", {"since": since, "max_lines": 50})
    check("log: lines since play", ok and data.get("lines") and data["lines"][0]["seq"] > since, data.get("next"))
    ok, data = call(mcp, toolset, "log", {"since": 0, "max_lines": 20, "errors_only": True})
    check("log: errors_only", ok and all(l["level"] != "info" for l in data.get("lines") or []), data.get("lines", [])[:1])
    ok, data = call(mcp, toolset, "stop", {})
    check("stop", ok and data.get("playing") is False, data)
    ok, data = call(mcp, toolset, "capture", {"source": "editor"})
    check("capture: the editor viewport", ok and base64.b64decode(data.get("image_base64") or "")[:4] == b"\x89PNG"
          and (data.get("width") or 0) > 0, {k: v for k, v in data.items() if k != "image_base64"})

    game_checks(mcp, toolset, packages)
    rig_checks(mcp, toolset, packages)
    shooter_checks(mcp, toolset, packages)

    set_mode(project, "plugin")  # the user's own project: Mixar's own levels only
    ok, data = call(mcp, toolset, "open_scene", {"scene": "/Game/ThirdPerson/Lvl_ThirdPerson"})
    check("open_scene: another level", ok, data)
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_PropYard", "name": "", "position": [0, 0, 0],
                                            "parent": "", "animation": ""})
    check("plugin mode: the user's level is not edited", not ok and "plugin mode" in data.get("error", ""), data)
    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2EPlugin",
                                                "overwrite": True})
    check("plugin mode: Mixar's own level, but not the main level", ok and not data.get("main"), data)
    set_mode(project, "owned")


SPINNER = "/Game/Mixar/Blueprints/BP_E2ESpinner"
SPIN_DSL = """
(event EventTick (DeltaSeconds)
  (Transformation|AddActorWorldRotation :self self
    :DeltaRotation (Math|Rotator|MakeRotator :Roll 0.0 :Pitch 0.0
                     :Yaw (* DeltaSeconds (Variables|Default|GetSpeed)))
    :bSweep false :bTeleport true))
"""


def playtest(mcp, toolset, steps) -> tuple[bool, dict]:
    return call(mcp, toolset, "playtest", {"steps": json.dumps(steps)})


def game_checks(mcp, toolset: str, packages: str) -> None:
    """U3: a template game around the course package, played and won; a
    Blueprint the agent writes, placed and running."""
    course = os.path.join(packages, "UEQA_Course")
    ok, data = call(mcp, toolset, "import_package", {"source_dir": course, "folder": "UEQA_Course"})
    check("import_package: the course", ok and len(data.get("objects") or []) == 11, data.get("objects"))
    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2ECourse", "template": "third_person",
                                                "player_position": [-6, 0, 1], "overwrite": True, "look": "sunset",
                                                "title": "Course", "objective": "Collect the 3 coins"})
    check("new_scene: third_person template", ok and data.get("game_mode") == "/Game/Mixar/Game/BP_MixarGameMode",
          data)
    check("new_scene: a look", data.get("look") == "sunset", data)
    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2EBadLook",
                                                "look": "noon"})
    check("new_scene: an unknown look is refused", not ok and "sunset" in data.get("error", ""), data)
    ok, tree = call(mcp, toolset, "scene_tree", {"max_nodes": 500})
    by_path = {n["path"]: n for n in tree.get("nodes") or []}
    for label in ("Sun", "Clouds", "PostProcess", "GameInfo", "Fog"):
        check(f"new_scene: the level has its {label}", label in by_path, sorted(by_path)[:30])
    check("scene_tree: components of a light", "LightComponent0" in (by_path.get("Sun", {}).get("components") or []),
          by_path.get("Sun"))
    ok, data = call(mcp, toolset, "set_property", {"node": "Sun", "property": "intensity", "value": json.dumps(7.5)})
    check("set_property: a component's property by its plain name",
          ok and data.get("set_on", "").lower().endswith(".intensity"), data)
    ok, data = call(mcp, toolset, "set_property", {"node": "Sun", "property": "LightComponent.color",
                                                   "value": json.dumps([255, 200, 150, 255])})
    check("set_property: a component by its base class, an alias", ok, data)
    ok, data = call(mcp, toolset, "set_property", {"node": "Sun", "property": "rotation",
                                                   "value": json.dumps([0, -20, -60])})
    check("set_property: rotation on the actor", ok, data)
    ok, data = call(mcp, toolset, "set_property", {"node": "GameInfo", "property": "Objective",
                                                   "value": json.dumps("Collect the 3 coins, then the flag")})
    check("set_property: the level's game info", ok, data)
    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2EBad", "template": "racing"})
    check("new_scene: an unknown template is refused", not ok and "third_person" in data.get("error", ""), data)
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_Course", "name": "", "position": [0, 0, 0],
                                            "parent": "", "animation": ""})
    check("place: the course", ok and data.get("actors") == 11, data)

    ok, data = call(mcp, toolset, "play", {"scene": "current"})
    check("play: the template game", ok and data.get("playing"), data)
    ok, data = playtest(mcp, toolset, [{"wait": 0.5}, {"hold": "move_forward", "seconds": 0.5}, {"press": "jump"}])
    steps = data.get("steps") or [{}, {}, {}]
    start, moved = steps[0].get("state", {}), steps[1].get("state", {})
    check("playtest: state from the GameMode", ok and start.get("total") == 3 and start.get("collected") == 0
          and start.get("on_floor") is True, start)
    check("playtest: hold moves the player (Enhanced Input)",
          moved.get("player_position", [0])[0] > start.get("player_position", [0])[0] + 1.0,
          [start.get("player_position"), moved.get("player_position")])
    check("playtest: press jump leaves the floor", steps[2].get("state", {}).get("on_floor") is False,
          steps[2].get("state"))
    ok, data = playtest(mcp, toolset, [{"press": "fly"}, {"wait": 0.1}])
    steps = data.get("steps") or [{}]
    check("playtest: an unknown action names the real ones", "move_forward" in (steps[0].get("error") or ""), data)
    check("playtest: a failed step does not end the run", len(steps) == 2 and data.get("errors") == 1, data)
    ok, data = playtest(mcp, toolset, [{"prove_loop": True}])
    loop = (data.get("steps") or [{}])[0]
    check("playtest: prove_loop wins (pickups, door, goal)", ok and loop.get("won") is True
          and not loop.get("unreached") and data.get("final_state", {}).get("doors_open") is True, loop)
    check("playtest: a fresh prove_loop win is the proof", data.get("proof") == "prove_loop_fresh"
          and loop.get("clean") is True, {k: data.get(k) for k in ("proof", "fresh_start")})
    ok, data = playtest(mcp, toolset, [{"state": True}])
    check("playtest: a run that begins won is no proof", data.get("proof") == "won_not_fresh"
          and data.get("fresh_start") is False, {k: data.get(k) for k in ("proof", "fresh_start")})
    ok, data = playtest(mcp, toolset, [{"inspect": {"node": "Door", "properties": ["rotation", "position"]}}])
    door = ((data.get("steps") or [{}])[0].get("values") or {})
    check("playtest: inspect reads the opened door", abs(abs((door.get("rotation") or [0, 0, 0])[2]) - 90) < 1,
          door)
    ok, data = playtest(mcp, toolset, [{"inspect": {"node": "Sun", "properties": ["LightComponent0.Intensity"]}}])
    values = (data.get("steps") or [{}])[0].get("values") or {}
    check("playtest: inspect reads a component's property", values.get("LightComponent0.Intensity") == 7.5, values)
    ok, data = call(mcp, toolset, "stop", {})
    character_checks(mcp, toolset, packages)

    ok, data = call(mcp, toolset, "blueprint", {"action": "docs", "path": "", "graph": "", "code": "", "name": "",
                                                "type": "", "parent": "", "query": ""})
    check("blueprint: docs", ok and "GRAMMAR" in data.get("docs", "") and "OnMixarEvent" in data.get("docs", ""))
    bp = {"path": SPINNER, "graph": "", "code": "", "name": "", "type": "", "parent": "", "query": ""}
    call(mcp, toolset, "remove_node", {"node": "Spinner"})
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "create", "parent": "Actor"})
    if not ok and "exists" in data.get("error", ""):
        ok = True
    check("blueprint: create", ok, data)
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "add_variable", "name": "Speed", "type": "float"})
    check("blueprint: add_variable", ok and "Speed" in (data.get("variables") or []), data)
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "find_nodes", "query": "AddActorWorldRotation"})
    check("blueprint: find_nodes", ok and "Transformation|AddActorWorldRotation" in (data.get("type_ids") or []),
          data)
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "write", "code": SPIN_DSL})
    check("blueprint: write compiles", ok and data.get("compiled"), data)
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "write", "code": "(event EventTick (Nope|Nothing))"})
    check("blueprint: a bad graph comes back as an error", not ok and data.get("error"), data)
    call(mcp, toolset, "blueprint", {**bp, "action": "write", "code": SPIN_DSL})
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "read"})
    check("blueprint: read", ok and "AddActorWorldRotation" in data.get("dsl", ""), data.get("dsl"))
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "create", "path": "/Game/Mixar/Game/BP_Mine"})
    check("blueprint: the template game's folder is Mixar Link's", not ok, data)
    ok, data = call(mcp, toolset, "blueprint", {**bp, "action": "create", "path": "/Game/ThirdPerson/BP_Mine"})
    check("blueprint: writes stay under /Game/Mixar", not ok, data)

    ok, data = call(mcp, toolset, "add_node", {"type": SPINNER, "name": "Spinner", "parent": "", "script": "",
                                               "position": [0, 3, 1]})
    check("add_node: the agent's Blueprint", ok and data.get("node") == "Spinner", data)
    ok, data = call(mcp, toolset, "add_node", {"type": "Nonsense", "name": "X", "parent": "", "script": "",
                                               "position": []})
    check("add_node: an unknown class is refused", not ok, data)
    ok, data = call(mcp, toolset, "set_property", {"node": "Spinner", "property": "Speed", "value": json.dumps(180)})
    check("set_property: a Blueprint variable", ok, data)
    ok, data = call(mcp, toolset, "set_property", {"node": "Spinner", "property": "position",
                                                   "value": json.dumps([1, 3, 1])})
    ok2, tree = call(mcp, toolset, "scene_tree", {"max_nodes": 500})
    spinner = next((n for n in tree.get("nodes") or [] if n["path"] == "Spinner"), {})
    check("set_property: position in the Blender frame", ok and spinner.get("position") == [1.0, 3.0, 1.0], spinner)
    ok, data = call(mcp, toolset, "set_property", {"node": "Spinner", "property": "NoSuchThing",
                                                   "value": json.dumps(1)})
    check("set_property: an unknown property is refused", not ok, data)
    call(mcp, toolset, "play", {"scene": "current"})
    ok, data = playtest(mcp, toolset, [{"inspect": {"node": "Spinner", "properties": ["rotation"]}}, {"wait": 1},
                                       {"inspect": {"node": "Spinner", "properties": ["rotation"]}}])
    yaws = [((s.get("values") or {}).get("rotation") or [0, 0, 0])[2] for s in (data.get("steps") or [])[::2]]
    check("the agent's Blueprint runs in the game", len(yaws) == 2 and abs(yaws[1] - yaws[0]) > 30, yaws)
    call(mcp, toolset, "stop", {})

    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2ETopDown", "template": "top_down",
                                                "set_main": False,
                                                "player_position": [-6, 0, 1], "overwrite": True})
    call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_Course", "name": "", "position": [0, 0, 0],
                                 "parent": "", "animation": ""})
    call(mcp, toolset, "play", {"scene": "current"})
    ok, data = playtest(mcp, toolset, [{"wait": 0.5}, {"hold": "move_forward", "seconds": 0.5}])
    steps = data.get("steps") or [{}, {}]
    a = steps[0].get("state", {}).get("player_position", [0, 0, 0])
    b = steps[-1].get("state", {}).get("player_position", [0, 0, 0])
    check("top_down: forward is north (Blender +Y)", b[1] > a[1] + 1.0 and abs(b[0] - a[0]) < 0.3, [a, b])
    call(mcp, toolset, "stop", {})


def _with_role(packages: str, name: str, role: str) -> str:
    """A copy of a package whose objects all take ``role``."""
    out = os.path.join(tempfile.mkdtemp(prefix="ueqa-role-"), f"{name}_{role}")
    shutil.copytree(os.path.join(packages, name), out)
    manifest_path = os.path.join(out, "manifest.json")
    manifest = json.load(open(manifest_path))
    for entry in manifest["engine"]["objects"]:
        entry["role"] = role
    json.dump(manifest, open(manifest_path, "w"))
    return out


def character_checks(mcp, toolset: str, packages: str) -> None:
    """0.4: the player plays as a rigged character (Mannequin clips
    retargeted), and an enemy without a patrol chases the player."""
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_Hero", "name": "Player",
                                            "position": [-8, 2, 0], "parent": "", "animation": ""})
    check("place: a player character takes its clips", ok and "MM_Idle" in data.get("animation", ""), data)
    enemy = _with_role(packages, "UEQA_Hero", "enemy")
    ok, data = call(mcp, toolset, "import_package", {"source_dir": enemy, "folder": "UEQA_Enemy"})
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_Enemy", "name": "Chaser",
                                            "position": [-6, 5, 0], "parent": "", "animation": JOG})
    check("place: an enemy character", ok, data)
    call(mcp, toolset, "play", {"scene": "current"})
    ok, data = playtest(mcp, toolset, [
        {"inspect": {"node": "BP_ThirdPersonCharacter0", "properties": ["CharacterMesh0.SkeletalMeshAsset"]}},
        {"inspect": {"node": "Chaser", "properties": ["position"]}}])
    steps = data.get("steps") or [{}, {}]
    body = (steps[0].get("values") or {}).get("CharacterMesh0.SkeletalMeshAsset", "")
    check("the player plays as the character", body.startswith("/Game/Mixar/UEQA_Hero/"), body)
    at = (steps[1].get("values") or {}).get("position") or [0, 5, 0]
    check("an enemy chases the player (from 5 m away)", at[1] < 3.0, at)
    call(mcp, toolset, "stop", {})
    call(mcp, toolset, "remove_node", {"node": "Mixar/Chaser"})
    call(mcp, toolset, "remove_node", {"node": "Mixar/Player"})
    shutil.rmtree(os.path.dirname(enemy), ignore_errors=True)


def shooter_checks(mcp, toolset: str, packages: str) -> None:
    """0.5: the shooter template — arena, rifle, a CT and a T model; rounds
    with bots, the player's rifle fires and reloads, bots fight."""
    for name in ("UEQA_Arena", "UEQA_Rifle"):
        ok, data = call(mcp, toolset, "import_package", {"source_dir": os.path.join(packages, name), "folder": name})
        check(f"import_package: {name}", ok, data.get("error"))
    enemy = _with_role(packages, "UEQA_Hero", "enemy")
    ok, data = call(mcp, toolset, "import_package", {"source_dir": enemy, "folder": "UEQA_Raider"})
    ok, data = call(mcp, toolset, "new_scene", {**NEW_SCENE, "name": "E2EShooter", "template": "shooter",
                                                "overwrite": True, "look": "day", "title": "Arena"})
    check("new_scene: shooter template",
          ok and data.get("game_mode") == "/Game/Mixar/Game/BP_MixarShooterGameMode", data)
    for scene, label in (("/Game/Mixar/UEQA_Arena", ""), ("/Game/Mixar/UEQA_Rifle", "Rifle"),
                         ("/Game/Mixar/UEQA_Hero", "CTModel"), ("/Game/Mixar/UEQA_Raider", "TModel")):
        ok, data = call(mcp, toolset, "place", {"scene": scene, "name": label, "position": [0, 0, 0],
                                                "parent": "", "animation": ""})
        check(f"place (shooter): {scene.rsplit('/', 1)[-1]}", ok, data)
        if label.endswith("Model"):
            check(f"place: {label} plays the retargeted rifle set", "MF_Rifle_Idle_ADS" in data.get("animation", ""),
                  data.get("animation"))
    ok, data = call(mcp, toolset, "play", {"scene": "current"})
    check("play: the shooter", ok and data.get("playing"), data)
    ok, data = playtest(mcp, toolset, [{"inspect": {"node": "BP_MixarBot_C"}}, {"god": True}, {"aim_at": [-17, 0, 1.2]}, {"fire": 1.0},
                                       {"reload": True}, {"wait": 4.5}, {"god": False}])
    steps = data.get("steps") or [{}] * 5
    start = steps[0] if steps else {}
    # the game runs before the first step: count the bots spawned (corpses stay), not the living
    check("shooter: round 1, 5 v 5 (4 CT bots and the player, 5 T bots)",
          start.get("state", {}).get("round") == 1 and len(start.get("similar") or []) == 9, start)
    fired = steps[3] if len(steps) > 3 else {}
    rate = fired.get("shots", 0) / max(fired.get("game_seconds") or 1.0, 0.05)
    check("shooter: the rifle fires (about 10 shots a second of game time)", 7 <= rate <= 13, fired or data)
    final = data.get("final_state") or {}
    check("shooter: reload fills the magazine", final.get("ammo") == 30 and final.get("reserve", 90) < 90, final)
    ok, png = call(mcp, toolset, "capture", {"source": "game", "max_width": 960})
    check("capture: first-person view", ok and (png.get("width") or 0) > 0)
    ok, data = playtest(mcp, toolset, [{"wait": 45}])
    final = data.get("final_state") or {}
    check("shooter: bots fight (fewer than 10 alive, or a round ended)",
          final.get("alive_ct", 5) + final.get("alive_t", 5) < 10 or final.get("score_ct", 0)
          + final.get("score_t", 0) > 0, final)
    call(mcp, toolset, "stop", {})
    shutil.rmtree(os.path.dirname(enemy), ignore_errors=True)


def rig_checks(mcp, toolset: str, packages: str) -> None:
    """A custom rig (no humanoid naming) imports skinned and places; an older
    package that lists no skeleton too; a package nothing of which matches
    is an error, not an empty success (uat4 2026-10-30: a scripted robot rig
    came in as a static mesh that could not be placed)."""
    robot = os.path.join(packages, "UEQA_Robot")
    ok, data = call(mcp, toolset, "import_package", {"source_dir": robot, "folder": "UEQA_Robot"})
    check("import_package: a custom rig imports skinned", ok and data.get("skeletal") is True
          and data.get("objects") == ["Robot_Body"] and "skipped" in (data.get("retarget") or {}), data)
    old = tempfile.mkdtemp(prefix="ueqa-old-")
    shutil.copytree(robot, os.path.join(old, "UEQA_RobotOld"))
    manifest_path = os.path.join(old, "UEQA_RobotOld", "manifest.json")
    manifest = json.load(open(manifest_path))
    manifest["engine"].pop("skeletons", None)
    json.dump(manifest, open(manifest_path, "w"))
    ok, data = call(mcp, toolset, "import_package", {"source_dir": os.path.join(old, "UEQA_RobotOld"),
                                                     "folder": "UEQA_RobotOld"})
    check("import_package: an older package's rig is found in its FBX", ok and data.get("skeletal") is True
          and data.get("objects") == ["Robot_Body"], data)
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_Robot", "name": "Robot",
                                            "position": [3, 3, 0], "parent": "", "animation": ""})
    ok2, tree = call(mcp, toolset, "scene_tree", {"max_nodes": 500})
    node = next((n for n in tree.get("nodes") or [] if n["path"].endswith("Robot")), {})
    check("place: the rigged robot", ok and node.get("type") == "SkeletalMeshActor", [data, node])
    shutil.copytree(os.path.join(packages, "UEQA_Course"), os.path.join(old, "UEQA_Wrong"))
    manifest_path = os.path.join(old, "UEQA_Wrong", "manifest.json")
    manifest = json.load(open(manifest_path))
    for entry in manifest["engine"]["objects"]:
        entry["name"] = "Nope_" + entry["name"]
    json.dump(manifest, open(manifest_path, "w"))
    ok, data = call(mcp, toolset, "import_package", {"source_dir": os.path.join(old, "UEQA_Wrong"),
                                                     "folder": "UEQA_Wrong"})
    check("import_package: nothing matching is an error", not ok and "none of it matches" in data.get("error", ""),
          data)
    shutil.rmtree(old, ignore_errors=True)
    ok, data = call(mcp, toolset, "add_node", {"type": "StaticMeshActor", "name": "Crate", "parent": "",
                                               "script": "", "position": [5, 5, 0.5]})
    ok, data = call(mcp, toolset, "set_property", {"node": "Crate", "property": "StaticMeshComponent.StaticMesh",
                                                   "value": json.dumps("/Engine/BasicShapes/Cube.Cube")})
    check("set_property: a component by its class name", ok, data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="the .uproject to test in")
    ap.add_argument("--editor", default="")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for the editor")
    ap.add_argument("--packages", default="", help="folder with UEQA_PropYard and UEQA_Hero (make_packages.py)")
    args = ap.parse_args()
    uproject = os.path.abspath(args.project)
    editor = args.editor or find_editor()
    install(uproject)
    before = content_snapshot(os.path.dirname(uproject))
    check("plugin installed", os.path.isfile(os.path.join(os.path.dirname(uproject), "Plugins", "MixarLink",
                                                          "MixarLink.uplugin")))

    proc = subprocess.Popen([editor, uproject, "-NoSplash", "-Unattended", "-NoSound"],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    discovery = os.path.join(LINK_DIR, f"unreal-{proc.pid}.json")
    try:
        deadline = time.time() + args.timeout
        while time.time() < deadline and not os.path.exists(discovery) and proc.poll() is None:
            time.sleep(1)
        check("discovery file written", os.path.exists(discovery))
        if not os.path.exists(discovery):
            return 1
        info = json.load(open(discovery))
        check("discovery: engine, transport, toolset",
              info.get("engine") == "unreal" and info.get("transport") == "unreal_mcp" and info.get("toolset"), info)
        check("discovery: port from the project's settings", info.get("port") == PORT, info.get("port"))
        check("discovery file private", (os.stat(discovery).st_mode & 0o077) == 0 or sys.platform == "win32")

        mcp = Mcp(info["port"], info.get("path") or "/mcp")
        while time.time() < deadline:
            try:
                init = mcp.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                              "clientInfo": {"name": "mixar-link-e2e", "version": "1"}})
                break
            except OSError:
                time.sleep(2)
        check("MCP initialize", bool(init and init.get("result")), init)
        toolset = info["toolset"]

        ok, reply, text = mcp.tool(toolset, "status", {})
        data = reply.get("data") or {}
        check("status", ok and reply.get("ok") and data.get("engine") == "unreal", text[:300])
        check("status: project and level", data.get("project_name") == info.get("project_name")
              and str(data.get("edited_scene", "")).startswith("/"), data)
        check("status: adapter version", data.get("adapter_version") == info.get("adapter_version"), data)
        check("status: lists its tools", {"status", "scene_tree"} <= set(data.get("tools") or []), data)

        ok, reply, text = mcp.tool(toolset, "scene_tree", {"max_nodes": 5})
        data = reply.get("data") or {}
        nodes = data.get("nodes") or []
        check("scene_tree", ok and reply.get("ok") and 0 < len(nodes) <= 5, text[:300])
        check("scene_tree: total and truncated", data.get("total", 0) >= len(nodes)
              and data.get("truncated") == (data.get("total", 0) > len(nodes)), data.get("total"))
        check("scene_tree: Blender-frame positions",
              all(isinstance(n.get("position"), list) and len(n["position"]) == 3 for n in nodes), nodes[:1])
        ok, reply, _ = mcp.tool(toolset, "scene_tree", {})
        check("scene_tree: max_nodes is optional", ok and reply.get("ok"))

        ok, _, text = mcp.tool(toolset, "no_such_tool", {})
        check("unknown tool refused", not ok and text, text)

        if args.packages:
            package_checks(mcp, toolset, os.path.abspath(args.packages), os.path.dirname(uproject))
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM if sys.platform != "win32" else signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
    if sys.platform != "win32":
        check("discovery file removed on close", not os.path.exists(discovery))
    if args.packages:
        game = os.path.join(os.path.dirname(uproject), "Content", "Mixar", "Game")
        for asset in ("Audio/S_MixarPickup.uasset", "Audio/S_MixarMusic.uasset", "FX/NS_MixarPickup.uasset",
                      "BP_MixarGameInfo.uasset"):
            check(f"template game: {asset}", os.path.isfile(os.path.join(game, asset)))
        changed = [p for p, v in content_snapshot(os.path.dirname(uproject)).items() if before.get(p) != v]
        changed += [p for p in before if not os.path.exists(os.path.join(os.path.dirname(uproject), "Content", p))]
        check("nothing under Content/ outside Content/Mixar changed", not changed, changed[:5])
    print(f"\n{'OK' if not failures else 'FAILED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
