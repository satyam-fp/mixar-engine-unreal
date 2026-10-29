"""The discovery file the Mixar desktop app reads to find this editor:
``~/.mixar/engine-link/unreal-<pid>.json``, written at start and removed when
the editor closes (a crash leaves it behind; the app skips a file whose port
does not answer).

Unreal's MCP server has no token of its own: it listens on 127.0.0.1 only and
refuses browser origins. The file carries ``token: ""`` and
``transport: "unreal_mcp"`` so the app speaks Unreal's ``call_tool`` envelope
to ``toolset``."""

import json
import os
import sys
import time

import unreal

from . import ADAPTER_VERSION

DEFAULT_PORT = 8000
SETTINGS_SECTION = "[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]"
_path = ""


def _settings_files() -> list:
    """The ini files that set the MCP server, lowest priority first: the
    project's defaults, then the user's Editor Preferences."""
    project = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())
    platform = {"darwin": "Mac", "win32": "Windows"}.get(sys.platform, "Linux")
    return [os.path.join(project, "Config", "DefaultEditorPerProjectUserSettings.ini"),
            os.path.join(project, "Saved", "Config", f"{platform}Editor", "EditorPerProjectUserSettings.ini")]


def _setting(key: str) -> str:
    """The last value of ``key`` in the MCP settings section (the class's
    properties are not exposed to Python)."""
    value = ""
    for path in _settings_files():
        try:
            lines = open(path, encoding="utf-8-sig").read().splitlines()
        except OSError:
            continue
        inside = False
        for line in lines:
            line = line.strip()
            if line.startswith("["):
                inside = line == SETTINGS_SECTION
            elif inside and line.split("=", 1)[0].strip() == key and "=" in line:
                value = line.split("=", 1)[1].strip()
    return value


def server_port() -> int:
    try:
        return int(_setting("ServerPortNumber") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def server_path() -> str:
    return _setting("ServerUrlPath") or "/mcp"


def info() -> dict:
    from .toolsets import TOOLSET

    return {
        "engine": "unreal",
        "version": unreal.SystemLibrary.get_engine_version(),
        "adapter_version": ADAPTER_VERSION,
        "project_name": unreal.SystemLibrary.get_game_name(),
        "pid": os.getpid(),
        "port": server_port(),
        "path": server_path(),
        "token": "",
        "transport": "unreal_mcp",
        "toolset": TOOLSET,
        "started_at": time.time(),
    }


def start() -> str:
    global _path
    folder = os.path.join(os.path.expanduser("~"), ".mixar", "engine-link")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"unreal-{os.getpid()}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(info(), fh)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    _path = path
    unreal.register_python_shutdown_callback(stop)
    unreal.log(f"[Mixar Link] {ADAPTER_VERSION} ready on 127.0.0.1:{server_port()}")
    return path


def stop() -> None:
    global _path
    if _path:
        try:
            os.remove(_path)
        except OSError:
            pass
        _path = ""
