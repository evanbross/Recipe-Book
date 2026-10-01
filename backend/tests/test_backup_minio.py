import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from backup_minio import object_local_path  # noqa: E402


def test_object_local_path_maps_key_under_objects_dir(tmp_path):
    result = object_local_path(tmp_path, "originals/abc123.jpg")
    assert result == tmp_path / "objects" / "originals" / "abc123.jpg"


def test_object_local_path_rejects_traversal_outside_out_dir(tmp_path):
    with pytest.raises(ValueError, match="unsafe object key"):
        object_local_path(tmp_path, "../../etc/passwd")


def test_object_local_path_rejects_absolute_style_escape(tmp_path):
    with pytest.raises(ValueError, match="unsafe object key"):
        object_local_path(tmp_path, "originals/../../../outside.jpg")
