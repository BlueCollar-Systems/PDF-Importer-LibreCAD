from __future__ import annotations

from unittest.mock import patch

import pytest

import build_release
import build_standalone
import build_windows_portable


@pytest.mark.parametrize(
    "reader",
    [
        build_release._read_version,
        build_standalone._read_version,
        build_windows_portable.read_version,
    ],
)
def test_release_builders_share_the_exact_product_version(reader) -> None:
    assert reader() == "1.0.67"


def test_source_release_refuses_to_publish_an_unknown_version() -> None:
    with patch.object(build_release.Path, "read_text", return_value="no version here"):
        with pytest.raises(RuntimeError, match="Could not read __version__"):
            build_release._read_version()


def test_standalone_release_refuses_to_publish_an_unknown_version() -> None:
    with patch.object(build_standalone.Path, "read_text", return_value="no version here"):
        with pytest.raises(RuntimeError, match="Could not read __version__"):
            build_standalone._read_version()
