# Mixar Link for Unreal

An Unreal Engine 5.8+ editor plugin that lets the [Mixar](https://mixar.app) agent
work in your Unreal project. It adds Mixar's toolset to Unreal's own
[Model Context Protocol](https://modelcontextprotocol.io) server (the
experimental `ModelContextProtocol` plugin that ships with the engine), beside
Epic's toolsets. Nothing in it runs arbitrary code: every tool is purpose-built.

The tools share their names and result shapes with
[Mixar Link for Godot](https://github.com/satyam-fp/mixar-engine-godot), so the
Mixar agent drives either engine with the same calls.

## Install

1. In the Mixar app, open the engine chip in the chat composer, pick the
   **Unreal Engine** tab and press **Connect Unreal**. It installs the latest
   release into a project you pick (or a new third-person project), enables the
   plugins below and opens the editor.
2. By hand: unzip [`MixarLink.zip`](https://github.com/satyam-fp/mixar-engine-unreal/releases/latest/download/MixarLink.zip)
   into your project's `Plugins/` folder, enable `ModelContextProtocol`,
   `AllToolsets`, `PythonScriptPlugin` and `EditorScriptingUtilities`, and turn
   on the MCP server (`Config/DefaultEditorPerProjectUserSettings.ini`):

   ```ini
   [/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]
   bAutoStartServer=True
   ServerPortNumber=9880
   ```

3. Keep the project open in the editor. The Mixar desktop app finds it on its own.

## How Mixar connects

At editor start the plugin registers its toolset and writes
`~/.mixar/engine-link/unreal-<pid>.json` (engine, project, the server's port and
path, the toolset name), readable only by you; it deletes the file when the
editor closes. Unreal's server listens on 127.0.0.1 only and refuses browser
origins; it has no token of its own.

A tool is called through the server's `call_tool` with
`toolset_name: "mixar_link.toolsets.MixarLinkTools"`. Each answers a JSON string,
`{"ok": true, "data": {…}}` or `{"ok": false, "error": "…"}`.

Positions are Blender's frame (right-handed, Z up, metres): Unreal
`(x, y, z)` cm is Blender `(x, -y, z) / 100`, and a yaw flips sign.

## Tools

| Tool | Does |
| --- | --- |
| `status` | Engine, project, the open level, the main level, whether the game runs |
| `scene_tree` | The open level's actors: outliner path, class, position, yaw, the mesh or Blueprint it instances, attachments |

Everything Mixar Link creates lives under `/Game/Mixar`.

## Test

```bash
python3 test/run_e2e.py --project /path/to/Game.uproject
```

copies the plugin into the project, opens the editor, checks discovery and every
tool over MCP, and closes the editor. Exit code 0 = every check passed.

## Release

`scripts/release.sh` zips `MixarLink/` and publishes it as a GitHub release
named after `VersionName` in `MixarLink.uplugin` (which must equal
`ADAPTER_VERSION`).
