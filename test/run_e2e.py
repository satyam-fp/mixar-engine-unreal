#!/usr/bin/env python3
"""End-to-end test of Mixar Link for Unreal against a real Unreal 5.8+ editor:
the plugin installed into a project, discovery, Unreal's MCP handshake, every
tool through ``call_tool``, and the discovery file removed on close.

    python3 test/run_e2e.py --project /path/to/Game.uproject [--editor /path/to/UnrealEditor]

The project's Plugins/MixarLink is replaced with this checkout's, the plugins
Mixar Link needs are enabled in the .uproject and the MCP server is turned on
(port 9880) in Config/DefaultEditorPerProjectUserSettings.ini. Exit code 0 =
every check passed. The editor is opened and closed by the test.
"""

from __future__ import annotations

import argparse
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
        os.makedirs(os.path.dirname(ini), exist_ok=True)
        with open(ini, "w", encoding="utf-8") as fh:
            fh.write(text)


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
        with urllib.request.urlopen(req, timeout=120) as resp:
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="the .uproject to test in")
    ap.add_argument("--editor", default="")
    ap.add_argument("--timeout", type=float, default=900.0, help="seconds to wait for the editor")
    args = ap.parse_args()
    uproject = os.path.abspath(args.project)
    editor = args.editor or find_editor()
    install(uproject)
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
    finally:
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM if sys.platform != "win32" else signal.CTRL_BREAK_EVENT)
            try:
                proc.wait(timeout=90)
            except subprocess.TimeoutExpired:
                proc.kill()
    if sys.platform != "win32":
        check("discovery file removed on close", not os.path.exists(discovery))
    print(f"\n{'OK' if not failures else 'FAILED'}: {len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
