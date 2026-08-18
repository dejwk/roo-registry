import sys
import tempfile
import unittest
from pathlib import Path


BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

from module_utils import parse_module_bazel, replace_module_version


class ModuleUtilsTest(unittest.TestCase):

    def parse(self, content):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_path = Path(temp_dir) / "MODULE.bazel"
            module_path.write_text(content, encoding="utf-8")
            return parse_module_bazel(module_path)

    def test_parse_module_bazel_accepts_single_line(self):
        name, version, dependencies = self.parse(
            'module(name = "roo_consumer", version = "4.5.6")\n'
            'bazel_dep(name = "roo_dep", version = "1.2.3")\n'
        )

        self.assertEqual("roo_consumer", name)
        self.assertEqual("4.5.6", version)
        self.assertEqual(["roo_dep@1.2.3"], [str(dep) for dep in dependencies])

    def test_parse_module_bazel_accepts_multiline_trailing_commas(self):
        name, version, dependencies = self.parse(
            """module(
    version = '4.5.6',
    name = "roo_consumer",
)

bazel_dep(
    version = "1.2.3",
    name = "roo_dep",
)
"""
        )

        self.assertEqual("roo_consumer", name)
        self.assertEqual("4.5.6", version)
        self.assertEqual(["roo_dep@1.2.3"], [str(dep) for dep in dependencies])

    def test_replace_module_version_preserves_multiline_formatting(self):
        original = """module(
    name = "roo_consumer",
    version = "4.5.6",
)
"""

        updated, changed = replace_module_version(original, "5.0.0")

        self.assertTrue(changed)
        self.assertEqual(original.replace("4.5.6", "5.0.0"), updated)


if __name__ == "__main__":
    unittest.main()
