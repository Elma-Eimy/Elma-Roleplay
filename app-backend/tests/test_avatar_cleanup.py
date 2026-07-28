from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.infrastructure import outbox_worker


class AvatarCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.avatar_root = Path(self.temp_dir.name) / "avatars"
        self.avatar_root.mkdir()
        self.root_patch = patch.object(
            outbox_worker.settings,
            "STORAGE_UPLOAD_AVATAR_DIR",
            str(self.avatar_root),
        )
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp_dir.cleanup()

    def test_delete_avatar_removes_unreferenced_managed_file(self):
        avatar = self.avatar_root / "character.png"
        avatar.write_bytes(b"png")

        with patch.object(
            outbox_worker,
            "_avatar_is_still_referenced",
            return_value=False,
        ):
            outbox_worker.handle_delete_avatar(
                json.dumps({"file_path": str(avatar)})
            )

        self.assertFalse(avatar.exists())

    def test_delete_avatar_keeps_file_still_referenced(self):
        avatar = self.avatar_root / "shared.png"
        avatar.write_bytes(b"png")

        with patch.object(
            outbox_worker,
            "_avatar_is_still_referenced",
            return_value=True,
        ):
            outbox_worker.handle_delete_avatar(
                json.dumps({"file_path": str(avatar)})
            )

        self.assertTrue(avatar.exists())

    def test_delete_avatar_refuses_path_outside_managed_root(self):
        outside = Path(self.temp_dir.name) / "outside.png"
        outside.write_bytes(b"png")

        with patch.object(
            outbox_worker,
            "_avatar_is_still_referenced",
        ) as reference_check:
            outbox_worker.handle_delete_avatar(
                json.dumps({"file_path": str(outside)})
            )

        self.assertTrue(outside.exists())
        reference_check.assert_not_called()

    def test_delete_avatar_is_idempotent_when_file_is_missing(self):
        missing = self.avatar_root / "missing.png"

        with patch.object(
            outbox_worker,
            "_avatar_is_still_referenced",
            return_value=False,
        ):
            outbox_worker.handle_delete_avatar(
                json.dumps({"file_path": str(missing)})
            )


if __name__ == "__main__":
    unittest.main()
