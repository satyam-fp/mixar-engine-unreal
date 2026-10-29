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
        with urllib.request.urlopen(req, timeout=600) as resp:
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

    ok, data = call(mcp, toolset, "new_scene", {"name": "E2EYard", "template": "", "player_position": [-13, 0, 1],
                                                "overwrite": True, "ground": True})
    check("new_scene", ok and data.get("scene") == "/Game/Mixar/Levels/E2EYard" and data.get("main"), data)
    ok, data = call(mcp, toolset, "new_scene", {"name": "E2EYard", "template": "", "player_position": []})
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
    check("capture: the editor viewport", ok and base64.b64decode(data.get("image_base64") or "")[:4] == b"\x89PNG",
          data.get("error"))

    set_mode(project, "plugin")  # the user's own project: Mixar's own levels only
    ok, data = call(mcp, toolset, "open_scene", {"scene": "/Game/ThirdPerson/Lvl_ThirdPerson"})
    check("open_scene: another level", ok, data)
    ok, data = call(mcp, toolset, "place", {"scene": "/Game/Mixar/UEQA_PropYard", "name": "", "position": [0, 0, 0],
                                            "parent": "", "animation": ""})
    check("plugin mode: the user's level is not edited", not ok and "plugin mode" in data.get("error", ""), data)
    ok, data = call(mcp, toolset, "new_scene", {"name": "E2EPlugin", "template": "", "player_position": [],
                                                "overwrite": True})
    check("plugin mode: Mixar's own level, but not the main level", ok and not data.get("main"), data)
    set_mode(project, "owned")


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
        changed = [p for p, v in content_snapshot(os.path.dirname(uproject)).items() if before.get(p) != v]
        changed += [p for p in before if not os.path.exists(os.path.join(os.path.dirname(uproject), "Content", p))]
        check("nothing under Content/ outside Content/Mixar changed", not changed, changed[:5])
    print(f"\n{'OK' if not failures else 'FAILED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
