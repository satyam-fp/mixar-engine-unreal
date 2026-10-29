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

   and set `bThrottleCPUWhenNotForeground=False` under
   `[/Script/UnrealEd.EditorPerformanceSettings]` there too: Mixar drives the
   editor while Mixar has the focus, and a throttled editor takes seconds per frame.
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
| `status` | Engine, project, the open level, the main level, whether the game runs, the project mode, `log_seq`, the tools this release has |
| `import_package` | A Mixar package (an `export_asset(engine="unreal")` folder) into `/Game/Mixar/<folder>`: one StaticMesh per object in its own local space (its pivot stays at its origin) with its `UCX_` hulls, complex-as-simple for mesh collision, its `mixar_*` tags as asset metadata. A rigged humanoid imports as a SkeletalMesh, and its bone map builds an IK Rig and an IK Retargeter from the project's UE5 Mannequin |
| `new_scene` | Makes `/Game/Mixar/Levels/<name>` with a sun, sky, fog and a PlayerStart (a 60 m floor on request), opens it, optionally sets it as the main level |
| `open_scene` / `save_scene` | Opens / saves a level |
| `place` | Puts a package into the open level, one actor per object at its origin, moved and turned as a whole, under the outliner folder `Mixar/<instance>`; tags ride as actor tags (`mixar_role=pickup` …), `mixar_body` sets mobility and physics. A character can loop an animation: a Mannequin clip is retargeted onto it first |
| `remove_node` | Removes an actor, or a placed package's folder |
| `scene_tree` | The open level's actors: outliner path, class, position, yaw, the mesh or Blueprint it instances, Mixar tags, attachments |
| `play` / `stop` | Play In Editor, answered once the player has a pawn; stop |
| `capture` | A PNG of the running game (`HighResShot`) or of the level editor's viewport (Epic's `CaptureViewport`, which renders with the editor in the background) |
| `log` | Editor and game log lines after a `log_seq`; `errors_only` keeps errors and warnings |

`play`, `stop` and `capture` answer asynchronously (`ToolCallAsyncResultString`),
so the editor keeps running while they wait.

Unreal's tool schema gives only numbers and bools a default. The defaults it
cannot carry (strings, lists) are published in the discovery file
(`defaults`), and the Mixar desktop fills them in.

### What Mixar may change

Everything Mixar Link creates lives under `/Game/Mixar` (packages, levels, the
Mannequin's IK Rig). `Config/DefaultMixarLink.ini` holds the project mode:

- `owned` — a game Mixar made. Mixar edits any level and sets the main level.
- `plugin` (the default) — your own project. Mixar edits only levels under
  `/Game/Mixar` and changes no project settings.

## Test

```bash
# Real engine packages, built with the Mixar desktop's own exporter in a stock Blender
Blender --background --factory-startup --python test/make_packages.py -- \
    <mixar client>/src/scripts /tmp/ue_pkgs <rigged character .glb>
python3 test/run_e2e.py --project /path/to/Game.uproject --packages /tmp/ue_pkgs
```

The test copies the plugin into the project, opens the editor, checks discovery
and every tool over MCP (40 props at their manifest origins, a Tripo character
looping a retargeted Mannequin jog, play, frames, log, the plugin-mode refusals,
nothing under `Content/` outside `Content/Mixar` changed) and closes the editor.
The project should come from the third-person template, which has the Mannequin.
Exit code 0 = every check passed.

## Release

`scripts/release.sh` zips `MixarLink/` and publishes it as a GitHub release
named after `VersionName` in `MixarLink.uplugin` (which must equal
`ADAPTER_VERSION`).
