"""Vertex-layer classes.

Each vertex attribute in a Ravenswatch mesh is stored as a separate
sub-object (oCVec3VertexLayer, oCVec2VertexLayer, etc — all deriving from
oIVertexLayer). The cooked file registers them in the class table and emits
one section per layer instance. Vtable + Serialize VAs are in
data/cooked_class_map.json. Schema TBD.
"""

from . import register
from .base import SchemaHandler

register(SchemaHandler(class_name="oCVec3VertexLayer", source_ext="bin"))
register(SchemaHandler(class_name="oIVertexLayer", source_ext="bin"))
