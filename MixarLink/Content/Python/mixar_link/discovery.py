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
import socket
import time

import unreal

from . import ADAPTER_VERSION, config

DEFAULT_PORT = 8000
SETTINGS_SECTION = "[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]"
_path = ""


def _setting(key: str) -> str:
    """``key`` in the MCP server's settings (the class's properties are not
    exposed to Python): the project's defaults, then the user's preferences."""
    return config.read_layered("EditorPerProjectUserSettings", SETTINGS_SECTION, key)


def server_port() -> int:
    try:
        return int(_setting("ServerPortNumber") or DEFAULT_PORT)
    except ValueError:
        return DEFAULT_PORT


def server_path() -> str:
    return _setting("ServerUrlPath") or "/mcp"


def info() -> dict:
    from .toolsets import ARG_DEFAULTS, JSON_ARGS, TOOLSET

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
        "defaults": ARG_DEFAULTS,
        "json_args": JSON_ARGS,
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
    _watch_server()
    return path


# The server can fail to bind right after an editor restart (the old socket
# lingers): Unreal logs it and serves nothing. Until the port answers, retry.
RETRY_EVERY_S = 2.0
RETRY_FOR_S = 120.0


def _listening(port: int) -> bool:
    try:
        socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
        return True
    except OSError:
        return False


def _watch_server() -> None:
    port, started = server_port(), time.time()
    state = {"handle": None, "next": started + RETRY_EVERY_S, "tries": 0}

    def tick(_delta: float) -> None:
        now = time.time()
        if now < state["next"]:
            return
        state["next"] = now + RETRY_EVERY_S
        if _listening(port) or now - started > RETRY_FOR_S:
            unreal.unregister_slate_post_tick_callback(state["handle"])
            if _listening(port):
                unreal.log(f"[Mixar Link] {ADAPTER_VERSION} ready on 127.0.0.1:{port}"
                           + (f" (after {state['tries']} server restarts)" if state["tries"] else ""))
            else:
                unreal.log_error(f"[Mixar Link] Unreal's MCP server is not listening on 127.0.0.1:{port}; "
                                 "Mixar cannot reach this editor (is another program using the port?).")
            return
        state["tries"] += 1
        unreal.SystemLibrary.execute_console_command(None, "ModelContextProtocol.StopServer")
        unreal.SystemLibrary.execute_console_command(None, f"ModelContextProtocol.StartServer {port}")

    state["handle"] = unreal.register_slate_post_tick_callback(tick)


def stop() -> None:
    global _path
    if _path:
        try:
            os.remove(_path)
        except OSError:
            pass
        _path = ""
