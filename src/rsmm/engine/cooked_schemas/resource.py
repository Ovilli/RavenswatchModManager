"""Parent-class section codecs.

Stage 5d finding (docs/RE_NOTES.md): `oIResource::Serialize` at
`0x1400c2240` is a no-op stub returning 1; it writes zero bytes. The
leading section's small u32 triple is emitted by `oCBinarySaver`'s
container pre-pass, not by this class. Round-trip is already byte-stable
via `rsmm.engine.cooked`, so a `RawHandler` passthrough is sufficient.
"""

from . import register
from .base import RawHandler

register(RawHandler("oIResource"))
register(RawHandler("oISerializable"))
register(RawHandler("oCShaderParamSet"))
