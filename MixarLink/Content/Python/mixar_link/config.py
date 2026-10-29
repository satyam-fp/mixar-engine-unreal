"""Reading and writing the project's ini files (Unreal does not expose its
config cache to Python), and the project mode.

The project mode decides what Mixar may change outside ``/Game/Mixar``:

- ``owned``: a game Mixar made (Connect Unreal's new project). Mixar edits
  any level and sets the project's main level.
- ``plugin``: the user's own project, the default. Mixar edits only levels
  under ``/Game/Mixar`` and changes no project settings.

Assets are always written under ``/Game/Mixar`` whatever the mode. The mode
lives in ``Config/DefaultMixarLink.ini`` (``[MixarLink] ProjectMode=``),
written by the Mixar desktop when it connects a project.
"""

import os
import sys

import unreal

MODE_SECTION = "[MixarLink]"


def project_dir() -> str:
    return unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())


def _platform() -> str:
    return {"darwin": "Mac", "win32": "Windows"}.get(sys.platform, "Linux")


def read(path: str, section: str, key: str) -> str:
    """The last ``key=`` value in ``section`` of one ini file, or ""."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return ""
    value, inside = "", False
    for line in lines:
        line = line.strip()
        if line.startswith("["):
            inside = line == section
        elif inside and "=" in line and line.split("=", 1)[0].strip() == key:
            value = line.split("=", 1)[1].strip()
    return value


def read_layered(name: str, section: str, key: str) -> str:
    """``key`` from the project's Default<name>.ini, overridden by the user's
    Saved/Config/<Platform>Editor/<name>.ini (Editor Preferences)."""
    value = ""
    for path in (os.path.join(project_dir(), "Config", f"Default{name}.ini"),
                 os.path.join(project_dir(), "Saved", "Config", f"{_platform()}Editor", f"{name}.ini")):
        value = read(path, section, key) or value
    return value


def write(path: str, section: str, values: dict) -> None:
    """Set ``values`` under ``section``, keeping everything else."""
    try:
        with open(path, encoding="utf-8-sig") as fh:
            lines = fh.read().splitlines()
    except OSError:
        lines = []
    start = next((i for i, line in enumerate(lines) if line.strip() == section), -1)
    if start < 0:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [section] + [f"{k}={v}" for k, v in values.items()]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].strip().startswith("[")), len(lines))
        body = lines[start + 1:end]
        remaining = dict(values)
        for i, line in enumerate(body):
            key = line.split("=", 1)[0].strip()
            if "=" in line and key in remaining:
                body[i] = f"{key}={remaining.pop(key)}"
        while body and not body[-1].strip():
            body.pop()
        body += [f"{k}={v}" for k, v in remaining.items()]
        lines = lines[:start + 1] + body + ([""] if end < len(lines) else []) + lines[end:]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def mode() -> str:
    value = read(os.path.join(project_dir(), "Config", "DefaultMixarLink.ini"), MODE_SECTION, "ProjectMode")
    return "owned" if value.lower() == "owned" else "plugin"
