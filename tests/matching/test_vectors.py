import math

import pytest

from jobscout.matching.vectors import cosine, dim, pack, unpack


def test_pack_unpack_roundtrip():
    vector = [0.5, -0.25, 0.125]
    restored = unpack(pack(vector))
    assert len(restored) == 3
    assert all(math.isclose(a, b, rel_tol=1e-6) for a, b in zip(vector, restored, strict=True))


def test_dim_counts_floats():
    assert dim(pack([1.0] * 768)) == 768
    assert dim(None) == 0
    assert dim(b"") == 0


def test_cosine_known_values():
    assert math.isclose(cosine([1.0, 0.0], [1.0, 0.0]), 1.0, rel_tol=1e-6)
    assert math.isclose(cosine([1.0, 0.0], [0.0, 1.0]), 0.0, abs_tol=1e-6)
    assert math.isclose(cosine([1.0, 0.0], [-1.0, 0.0]), -1.0, rel_tol=1e-6)
    assert math.isclose(cosine([3.0, 4.0], [3.0, 4.0]), 1.0, rel_tol=1e-6)


def test_cosine_zero_vector_is_zero():
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_cosine_length_mismatch_raises():
    with pytest.raises(ValueError, match="length"):
        cosine([1.0], [1.0, 2.0])
