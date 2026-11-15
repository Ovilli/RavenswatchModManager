"""oCMesh schema (v1.2). One per submesh inside oCGeometry+0x88. Holds
material ref + oCMeshBuffer + optional name. See https://docs.rsmm.me/reverse-engineering/notes/.
Decoder/encoder deferred until oCMeshBuffer is fully reversed.
"""

from . import register
from .base import SchemaHandler

register(SchemaHandler(class_name="oCMesh", source_ext="gltf"))
