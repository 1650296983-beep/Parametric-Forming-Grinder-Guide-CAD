"""Host-independent envelopes for numeric CAD annotations."""

from functools import lru_cache
from pathlib import Path

import ezdxf
import matplotlib
from ezdxf import bbox
from ezdxf.fonts import fonts


MEASUREMENT_FONT = "STIXGeneral.ttf"


@lru_cache(maxsize=1)
def _measurement_document():
    fonts.font_manager.scan_folder(Path(matplotlib.get_data_path()) / "fonts" / "ttf")
    doc = ezdxf.new("R2010")
    doc.styles.get("Standard").dxf.font = MEASUREMENT_FONT
    return doc


def annotation_text_extents(entity):
    """Measure a private copy with Matplotlib's bundled STIX font metrics.

    The drawing retains its template font, text height, width, alignment and
    rotation. Only layout calculations use the same bundled font on every host,
    so installed Arial/SHX substitutes cannot change annotation coordinates.
    """
    measured = entity.copy()
    measured.doc = _measurement_document()
    measured.dxf.style = "Standard"
    return bbox.extents([measured])
