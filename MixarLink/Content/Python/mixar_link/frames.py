"""Blender's frame (right-handed, Z up, metres) <-> Unreal's (left-handed,
Z up, centimetres). Unreal's FBX/glTF importers map Blender (x, y, z) to
(x, -y, z) x 100, so a position the agent reads in Mixar is the same place
after these conversions; a yaw about the up axis flips sign with Y."""

CM = 100.0


def _r(value: float) -> float:
    return round(value, 4) + 0.0  # + 0.0 turns -0.0 into 0.0


def to_blender(location) -> list:
    """An unreal.Vector (cm) as a Blender-frame [x, y, z] in metres."""
    return [_r(location.x / CM), _r(-location.y / CM), _r(location.z / CM)]


def from_blender(position) -> tuple:
    """A Blender-frame [x, y, z] in metres as Unreal (x, y, z) in cm."""
    x, y, z = (float(v) for v in position)
    return x * CM, -y * CM, z * CM


def yaw_to_blender(yaw_deg: float) -> float:
    return round(-yaw_deg, 3) + 0.0


def yaw_from_blender(yaw_deg: float) -> float:
    return -float(yaw_deg)
