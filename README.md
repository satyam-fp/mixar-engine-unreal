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
   `AllToolsets` (it brings `EditorToolset`, whose Blueprint tools the template
   game and the `blueprint` tool use), `PythonScriptPlugin` and
   `EditorScriptingUtilities`, and turn
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
| `new_scene` | Makes `/Game/Mixar/Levels/<name>` with a sun, sky, fog and a PlayerStart (a 60 m floor on request), opens it, optionally sets it as the main level. `template` makes it a playable game (below) |
| `open_scene` / `save_scene` | Opens / saves a level |
| `place` | Puts a package into the open level, one actor per object at its origin, moved and turned as a whole, under the outliner folder `Mixar/<instance>`; tags ride as actor tags (`mixar_role=pickup` …), `mixar_body` sets mobility and physics. A character can loop an animation: a Mannequin clip is retargeted onto it first |
| `remove_node` | Removes an actor, or a placed package's folder |
| `add_node` | Spawns an actor of a built-in class (`PointLight`, `TriggerBox`, `TextRenderActor` …) or of a Blueprint under `/Game/Mixar`, at a Blender-frame position, optionally attached |
| `set_property` | Sets one property of an actor or of a component (`Component.Property`), a Blueprint variable included. `position` / `yaw_deg` are Blender's frame; other values Unreal's own (lists become vectors, rotators `[roll, pitch, yaw]` and colours; paths load assets and classes; enums by name) |
| `blueprint` | Makes, reads and writes Blueprints with Epic's EditorToolset: graphs in its S-expression DSL (`docs` prints it), variables, function parameters, node-type and pin lookup, compile. Writing an `(event …)` / `(fn …)` form replaces that part of the graph; a write compiles and returns compile errors. Writes only under `/Game/Mixar`, never in `/Game/Mixar/Game`, and not while the game runs |
| `scene_tree` | The open level's actors: outliner path, class, position, yaw, the mesh or Blueprint it instances, Mixar tags, attachments |
| `play` / `stop` | Play In Editor, answered once the player has a pawn; stop |
| `capture` | A PNG of the running game (`HighResShot`) or of the level editor's viewport (Epic's `CaptureViewport`, which renders with the editor in the background) |
| `log` | Editor and game log lines after a `log_seq`; `errors_only` keeps errors and warnings |
| `playtest` | Plays the running game with scripted steps and returns the game state after each: `hold` / `press` an input action, `wait`, `walk_to` a Blender-frame point (routed over the navigation mesh; reached / stuck / timed_out / no_path), `prove_loop` (every pickup nearest first, then the goal: `won`, `unreached`), `inspect` an actor's live properties, `state` |

`play`, `stop`, `capture` and `playtest` answer asynchronously
(`ToolCallAsyncResultString`), so the editor keeps running while they wait.

Unreal's tool schema gives only numbers and bools a default. The defaults it
cannot carry (strings, lists) are published in the discovery file
(`defaults`), and the Mixar desktop fills them in. Arguments of any JSON shape
(`playtest`'s `steps`, `set_property`'s `value`) travel as one JSON-encoded
string; the discovery file lists them (`json_args`).

### The template game

`new_scene(template=…)` runs the level on a GameMode Mixar Link builds once per
project (and rebuilds in place after an upgrade) under `/Game/Mixar/Game`,
written with Epic's Blueprint graph DSL from `mixar_link/game_spec.py`:

- `BP_MixarGameMode` (child of the project's `BP_ThirdPersonGameMode`, so the
  third-person character and its Enhanced Input come along) keeps the rules
  the `mixar_role` tags drive, as Mixar Link for Godot's game does: pickups
  spin and are collected on touch, all collected opens the doors (`mixar_pivot`
  `hinge_*` swings 90°, `slide_*` slides), the goal wins once they are open,
  hazards and enemies (patrolling 4 m with `slide_*`) and a 25 m fall respawn
  at the spawn or the last checkpoint, triggers report on entry;
- `BP_MixarGameMode_TopDown` (camera above, W = north) and
  `BP_MixarGameMode_Platformer` (side view from Blender −Y, the player keeps
  its lane) change only the camera and movement;
- `BP_MixarHUD` draws the level's title card (its `GameInfo` actor: Title,
  Objective, Music, Ambience), the collected count, a timer, a hit flash and an
  end screen. The game plays synthesised sounds (`Resources/Sounds`,
  `scripts/make_sounds.py`), wind and music, and Niagara bursts for pickups,
  hits and the win; an `enemy` without a pivot chases the player; a
  `mixar_role=player` humanoid replaces the Mannequin (idle / run / fall clips
  retargeted onto it). `new_scene` takes `look` (day, sunset, dawn, night,
  overcast), `floating` (ground and clouds below the level), `title`,
  `objective`.

`template="shooter"` (0.5) is a round-based first-person tactical shooter,
from `mixar_link/shooter_spec.py`:

- `BP_MixarShooterGameMode` (a child of `BP_MixarGameMode`): CT and T spawn on
  `spawn` markers tagged `mixar_team` `ct` / `t`; rounds end by elimination or
  time (CT), first to `RoundsToWin` (GameInfo; also `BotsPerTeam`,
  `RoundSeconds`); a kill feed;
- `BP_MixarShooterPlayer` (child of the third-person character): first person
  with a view model (the player character's own mesh, head and legs hidden,
  attached to the camera), fire / reload / walk / crouch on the mouse and
  R / Shift / Ctrl, recoil climb with partial recovery, spray and movement
  spread, 30 / 90 ammo, armor, a death camera;
- `BP_MixarBot`: Characters on the navigation mesh that move toward the enemy
  spawn or mid, turn on the nearest enemy in sight, react, fire bursts with
  spread, die with a death clip;
- `BP_MixarShooterHUD`: crosshair, hit marker, health / armor, ammo, score,
  round timer, alive counts, kill feed, banners.

Placed packages give the game its art: a rigged humanoid `player` / `ally` /
`enemy` becomes its team's model (the Mannequin rifle set retargeted onto
it, root locked), a `weapon` mesh (origin on the grip, barrel toward Blender
−Y) the rifle everyone holds; both stay as hidden stand-ins. The rifle's hold
is measured from the live pose each frame (right hand on the grip, barrel
along the aim), and the view model is placed from the camera so the eyes sit
at GameInfo `ViewEye`.

They are ordinary Blueprints in the project, so a packaged game carries them.
Other Blueprints talk to the rules through the GameMode's
`OnMixarEvent(Event, Source)` and report values to playtests with
`ReportState(Key, Value)`. The level also gets a `MixarNavigation` volume, fitted
to the level at each `play`, whose navigation mesh rebuilds as doors open.

The first template build takes about a minute (Epic's transpiler looks every
node type up); later levels reuse it. It needs the project's
`/Game/ThirdPerson` (every project made from the Third Person template has it).

### What Mixar may change

Everything Mixar Link creates lives under `/Game/Mixar` (packages, levels, the
Mannequin's IK Rig). `Config/DefaultMixarLink.ini` holds the project mode:

- `owned` — a game Mixar made. Mixar edits any level and sets the main level.
- `plugin` (the default) — your own project. Mixar edits only levels under
  `/Game/Mixar` and changes no project settings.

Blueprints are written under `/Game/Mixar` in both modes.

## Test

```bash
# Real engine packages, built with the Mixar desktop's own exporter in a stock Blender
Blender --background --factory-startup --python test/make_packages.py -- \
    <mixar client>/src/scripts /tmp/ue_pkgs <rigged character .glb>
python3 test/run_e2e.py --project /path/to/Game.uproject --packages /tmp/ue_pkgs
```

The test copies the plugin into the project, opens the editor, checks discovery
and every tool over MCP (40 props at their manifest origins, a Tripo character
looping a retargeted Mannequin jog, play, frames, log; a third-person template
game around the course package won by `prove_loop`, input moving the player, a
Blueprint written through `blueprint`, placed with `add_node`, tuned with
`set_property` and turning in play, top-down movement; the plugin-mode
refusals, nothing under `Content/` outside `Content/Mixar` changed) and closes
the editor.
The project should come from the third-person template, which has the Mannequin.
Exit code 0 = every check passed.

## Release

`scripts/release.sh` zips `MixarLink/` and publishes it as a GitHub release
named after `VersionName` in `MixarLink.uplugin` (which must equal
`ADAPTER_VERSION`).
