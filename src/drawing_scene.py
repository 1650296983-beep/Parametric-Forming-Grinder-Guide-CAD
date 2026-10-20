"""Small SVG-compatible adapter of the actual CAD writers' entities.

No product geometry is calculated here. Arcs and bulges are flattened by ezdxf
at 0.002 mm chord tolerance; source entities keep stable IDs across stage views.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from math import isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import ezdxf
from ezdxf import path as dxf_path
from ezdxf.tools.text import plain_text

COLORS = {1: '#ef6464', 2: '#e7d57b', 3: '#5ad38e', 4: '#64cce0', 5: '#849dea', 6: '#d18ce0', 7: '#e3e9ef', 8: '#a3adb8'}
EXCLUDED = ('DEBUG', 'REFERENCE', 'CONTROL', 'FORMULA')


def _group(layer: str, kind: str) -> str:
    if 'CENTER' in layer:
        return 'center'
    if kind in {'DIMENSION', 'TEXT', 'MTEXT'} or 'DIM' in layer:
        return 'dimensions'
    if layer == 'PARAM_SLOT' or 'CAVITY' in layer or layer.startswith('SIDE_DERIVED'):
        return 'cavity'
    return 'outline'


def _entities(entity: Any, group: str | None = None, identity: str = '') -> list[dict[str, Any]]:
    kind, layer = entity.dxftype(), entity.dxf.get('layer', '0')
    if any(item in layer.upper() for item in EXCLUDED):
        return []
    group = group or _group(layer, kind)
    identity = identity or str(entity.dxf.get('handle', 'entity'))
    if kind in {'DIMENSION', 'INSERT'}:
        try:
            values = [item for index, child in enumerate(entity.virtual_entities()) for item in _entities(child, group, f'{identity}-{index}')]
            if kind == 'DIMENSION':
                explicit_label = entity.dxf.get('text', '').strip()
                if explicit_label and '<>' not in explicit_label:
                    for value in values:
                        if value['kind'] == 'text':
                            value['text'] = plain_text(explicit_label)
                            break
            return values
        except (AttributeError, TypeError, ValueError):
            return []
    color_index = entity.dxf.get('color', 256)
    if color_index in {0, 256}:
        try:
            color_index = entity.doc.layers.get(layer).dxf.color
        except (AttributeError, ezdxf.DXFTableEntryError):
            color_index = 7
    color = COLORS.get(abs(color_index), COLORS[7])
    base = {'id': identity, 'group': group, 'color': color}
    if kind in {'TEXT', 'MTEXT'}:
        insert = entity.dxf.insert
        text = entity.plain_text() if hasattr(entity, 'plain_text') else entity.dxf.text
        return [{**base, 'kind': 'text', 'position': [insert.x, -insert.y], 'text': text, 'height': float(entity.dxf.get('char_height' if kind == 'MTEXT' else 'height', 1)), 'rotation': -float(entity.dxf.get('rotation', 0))}]
    if kind not in {'LINE', 'ARC', 'CIRCLE', 'LWPOLYLINE', 'POLYLINE', 'SPLINE', 'ELLIPSE', 'SOLID'}:
        return []
    try:
        vertices = entity.flattening(sagitta=0.002) if kind in {'ARC', 'CIRCLE'} else dxf_path.make_path(entity).flattening(distance=0.002)
        points = [[point.x, -point.y] for point in vertices]
    except (TypeError, ValueError, AttributeError, NotImplementedError):
        return []
    if len(points) < 2 or not all(isfinite(v) for point in points for v in point):
        return []
    linetype = entity.dxf.get('linetype', 'BYLAYER')
    if linetype == 'BYLAYER':
        try:
            linetype = entity.doc.layers.get(layer).dxf.linetype
        except (AttributeError, ezdxf.DXFTableEntryError):
            pass
    return [{**base, 'kind': 'polyline', 'points': points, 'dash': linetype.upper() not in {'CONTINUOUS', 'BYLAYER', 'BYBLOCK'}}]


def _bounds(primitives: list[dict]) -> list[float]:
    points = [point for item in primitives for point in (item['points'] if item['kind'] == 'polyline' else [item['position']])]
    if not points:
        return [0, 0, 1, 1]
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs) if max(xs) > min(xs) else min(xs)+1, max(ys) if max(ys) > min(ys) else min(ys)+1]



def _dimension_geometry_points(entity: Any) -> list[tuple[float, float]]:
    """Use attachment geometry, never leader/text extents, to choose a view.

    Radius/diameter defpoint is the circle centre and may lie in another view;
    defpoint4 is the actual arrow endpoint on the measured circular surface.
    """
    dimtype = entity.dxf.dimtype & 15
    names = ('defpoint4',) if dimtype in {3, 4} else ('defpoint2', 'defpoint3', 'defpoint4', 'defpoint5')
    points = []
    for name in names:
        value = entity.dxf.get(name)
        if value is not None and isfinite(value.x) and isfinite(value.y):
            points.append((value.x, value.y))
    return points


def _dimension_attaches_in(entity: Any, region: tuple[float, float, float, float]) -> bool:
    left, right, bottom, top = region
    points = _dimension_geometry_points(entity)
    return bool(points) and all(left-5 <= x <= right+5 and bottom-5 <= y <= top+5 for x, y in points)

def scene_from_dxf(filename: Path, machine: Any, *, source: str) -> dict[str, Any]:
    doc = ezdxf.readfile(filename)
    return scene_from_document(doc, machine, source=source)


def scene_from_document(doc: Any, machine: Any, *, source: str) -> dict[str, Any]:
    items = [(entity, _entities(entity)) for entity in doc.modelspace()]
    items = [(entity, values) for entity, values in items if values]
    views = []
    if machine.guide_sections == 2:
        from .dual_guide_engine import DualGuideTemplateEngine
        template = DualGuideTemplateEngine(machine).build_template()
        regions = []
        for index, section in enumerate((template.guide_section_1, template.guide_section_2), 1):
            anchor = section.anchor
            regions.append((f'section_{index}', f'第 {index} 节截面', (anchor.left-12, anchor.right+12, anchor.bottom-10, anchor.top+12), False))
            regions.append((f'side_{index}', f'第 {index} 节侧视', section.side_bounds, True))
        regions.append(('assembly', '总装侧视', template.assembly_side_bounds, True))
        for identity, label, (left, right, bottom, top), side in regions:
            padding = 15 if side else 0
            selected = []
            for entity, values in items:
                layer = entity.dxf.get('layer', '')
                if side and not (layer.startswith('SIDE') or entity.dxftype() == 'DIMENSION'):
                    continue
                if not side and layer.startswith('SIDE'):
                    continue
                if entity.dxftype() == 'DIMENSION':
                    if _dimension_attaches_in(entity, (left, right, bottom, top)):
                        selected.extend(values)
                    continue
                bounds = _bounds(values)
                if bounds[0] >= left-padding and bounds[2] <= right+padding and bounds[1] >= -top-padding and bounds[3] <= -bottom+padding:
                    selected.extend(values)
            if selected:
                views.append({'id': identity, 'label': label, 'bounds': _bounds(selected), 'primitives': selected})
    else:
        cavity = [value for entity, values in items if entity.dxf.get('layer', '') == 'PARAM_SLOT' for value in values]
        cavity_bounds = _bounds(cavity)
        center_x = (cavity_bounds[0] + cavity_bounds[2]) / 2
        section_region = (center_x-machine.section_outer_width/2-22, cavity_bounds[1]-22, center_x+machine.section_outer_width/2+22, cavity_bounds[3]+22)
        layout = machine.side_layout
        side_region = (layout.left_x-35, -layout.upper_y-35, layout.right_x+35, -layout.lower_y+35)
        for identity, label, side, region in [('section_1', '导轨截面', False, section_region), ('side_1', '导轨侧视', True, side_region)]:
            selected = []
            for entity, values in items:
                layer = entity.dxf.get('layer', '')
                if layer.startswith('SIDE') != side:
                    continue
                if not side and layer not in {'FIXED_TEMPLATE', 'PARAM_SLOT', 'SECTION_CENTER', 'DIMENSION'}:
                    continue
                if entity.dxftype() == 'DIMENSION':
                    selected.extend(values)
                    continue
                bounds = _bounds(values)
                if bounds[0] >= region[0] and bounds[1] >= region[1] and bounds[2] <= region[2] and bounds[3] <= region[3]:
                    selected.extend(values)
            if selected:
                views.append({'id': identity, 'label': label, 'bounds': _bounds(selected), 'primitives': selected})
    return {'source': source, 'units': 'mm', 'coordinate_system': 'svg_y_down', 'views': views}


def preview_scene(profile: Any, machine: Any) -> dict[str, Any]:
    """Disposable actual writer output, never a retained formal artifact."""
    with TemporaryDirectory(prefix='cad-scene-') as directory:
        path = Path(directory) / 'preview.dxf'
        if machine.guide_sections == 2:
            from .dual_guide_engine import DualGuideTemplateEngine
            DualGuideTemplateEngine(machine).write_dxf(profile, path, output_mode='debug')
        else:
            from .dxf_writer import write_dxf
            write_dxf(profile, path, output_mode='debug', machine_id=machine.machine_id, machine_config_override=machine)
        return scene_from_dxf(path, machine, source='parametric_preview')


def parsed_values(value: Any) -> dict[str, Any]:
    return asdict(value) if is_dataclass(value) else {}
