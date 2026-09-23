"""Float vectors packed into the ``bytes`` columns, plus cosine similarity.

``array("f")`` keeps this dependency-free: 4 bytes per dimension, native float32.
At a few hundred jobs the pure-Python dot product costs milliseconds.
"""

import math
from array import array
from collections.abc import Sequence

_TYPECODE = "f"
_BYTES_PER_FLOAT = 4


def pack(vector: Sequence[float]) -> bytes:
    return array(_TYPECODE, vector).tobytes()


def unpack(blob: bytes) -> list[float]:
    values = array(_TYPECODE)
    values.frombytes(blob)
    return list(values)


def dim(blob: bytes | None) -> int:
    """Number of floats in a stored vector; 0 when absent."""
    if not blob:
        return 0
    return len(blob) // _BYTES_PER_FLOAT


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        raise ValueError(f"vector length mismatch: {len(a)} != {len(b)}")
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
