"""oCMeshBuffer schema (v1.4). Vertex + index buffer for one submesh. Lives
inside oCMesh+0x70. Bulk of mesh-modding payload. Schema in progress — see
Stage 5c in docs/RE_NOTES.md.
"""

from . import register
from .base import SchemaHandler

register(SchemaHandler(class_name="oCMeshBuffer", source_ext="bin"))
