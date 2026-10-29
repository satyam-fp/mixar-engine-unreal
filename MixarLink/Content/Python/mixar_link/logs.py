"""The editor's log, read from its log file. A line's ``seq`` is the file's
byte offset at the line's end, so ``status``/``play`` hand out the file size
as ``log_seq`` and ``log(since=…)`` returns the lines written after it — the
editor's and the running game's (Play In Editor logs into the same file)."""

import os

import unreal

MAX_READ = 1 << 20
MAX_TEXT = 400


def path() -> str:
    folder = unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_log_dir())
    return os.path.join(folder, f"{unreal.SystemLibrary.get_game_name()}.log")


def latest() -> int:
    try:
        return os.path.getsize(path())
    except OSError:
        return 0


def _level(text: str) -> str:
    if "Error:" in text or ": Fatal" in text:
        return "error"
    if "Warning:" in text:
        return "warning"
    return "info"


def since(seq: int, max_lines: int = 200, errors_only: bool = False) -> dict:
    """{"lines": [{seq, level, text}], "next", "more", "dropped"}; a file
    shorter than ``seq`` (a new editor session) is read from its start."""
    size = latest()
    start = seq if 0 <= seq <= size else 0
    try:
        with open(path(), "rb") as fh:
            fh.seek(start)
            raw = fh.read(MAX_READ)
    except OSError:
        return {"lines": [], "next": start, "more": False, "dropped": 0}
    cut = raw.rfind(b"\n") + 1  # whole lines only
    lines, full, offset = [], False, start
    for line in raw[:cut].split(b"\n")[:-1]:
        offset += len(line) + 1
        text = line.decode("utf-8", "replace").rstrip("\r")
        level = _level(text)
        if not text or (errors_only and level == "info"):
            continue
        if len(lines) >= max_lines:
            full = True
            break
        lines.append({"seq": offset, "level": level, "text": text[:MAX_TEXT]})
    nxt = lines[-1]["seq"] if full else start + cut
    return {"lines": lines, "next": nxt, "more": full or nxt < size, "dropped": 0}
