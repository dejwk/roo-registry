import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock


BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

import post_release as post_release_module


class PostReleaseTest(unittest.TestCase):

    def test_roo_testing_skips_platformio_publish(self):
        with (
            mock.patch.object(
                post_release_module, "clean_and_pull_module", return_value=True
            ),
            mock.patch.object(
                post_release_module, "get_module_version", return_value="2.0.2"
            ),
            mock.patch.object(
                post_release_module, "add_to_registry", return_value=True
            ),
            mock.patch.object(
                post_release_module, "generate_dependency_graph", return_value=True
            ),
            mock.patch.object(
                post_release_module, "amend_commit_with_graph", return_value=True
            ),
            mock.patch.object(
                post_release_module, "push_registry_changes", return_value=True
            ),
            mock.patch.object(
                post_release_module, "publish_to_platformio") as publish,
            mock.patch.object(post_release_module.Path, "exists", return_value=True),
            mock.patch.object(post_release_module.Path, "is_dir", return_value=True),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertTrue(post_release_module.post_release("roo_testing"))

        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
