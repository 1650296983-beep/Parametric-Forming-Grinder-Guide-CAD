from __future__ import annotations


DIMENSION_ROLE_APPID = "CAD_DIM_ROLE"

SECTION_CENTER_OPENING = "section_center_opening"
LOWER_WHEEL_NOTCH_OPENING = "lower_wheel_notch_opening"
LOWER_WHEEL_KEY_PROCESS_HEIGHT = "lower_wheel_key_process_height"
UPPER_WHEEL_KEY_PROCESS_HEIGHT = "upper_wheel_key_process_height"
UPPER_WHEEL_LOCAL_CUT_IN_DEPTH = "upper_wheel_local_cut_in_depth"

REQUIRED_BLOCK_TO_TILE_DIMENSION_ROLES = (
    SECTION_CENTER_OPENING,
    LOWER_WHEEL_NOTCH_OPENING,
    LOWER_WHEEL_KEY_PROCESS_HEIGHT,
    UPPER_WHEEL_KEY_PROCESS_HEIGHT,
    UPPER_WHEEL_LOCAL_CUT_IN_DEPTH,
)

REQUIRED_BLOCK_TO_BREAD_DIMENSION_ROLES = (
    LOWER_WHEEL_KEY_PROCESS_HEIGHT,
    UPPER_WHEEL_KEY_PROCESS_HEIGHT,
)


def set_dimension_role(entity, role: str) -> None:
    doc = getattr(entity, "doc", None)
    if doc is None:
        raise ValueError("Dimension must be attached to a DXF document before assigning a role.")
    if DIMENSION_ROLE_APPID not in doc.appids:
        doc.appids.add(DIMENSION_ROLE_APPID)
    entity.set_xdata(DIMENSION_ROLE_APPID, [(1000, role)])


def get_dimension_role(entity) -> str | None:
    try:
        tags = entity.get_xdata(DIMENSION_ROLE_APPID)
    except Exception:
        return None
    for tag in tags:
        if tag.code == 1000:
            return str(tag.value)
    return None
