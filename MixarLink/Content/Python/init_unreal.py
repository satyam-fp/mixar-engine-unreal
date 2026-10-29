"""Unreal runs this at editor start (any init_unreal.py on a plugin's Python
path): register Mixar Link's toolset with the editor's MCP server and tell the
Mixar desktop app where that server is."""

import unreal

try:
    from mixar_link import discovery, toolsets

    toolsets.registration.register()
    discovery.start()
except Exception as exc:  # noqa: BLE001 - a broken link must never stop the editor
    unreal.log_error(f"[Mixar Link] failed to start: {exc}")
