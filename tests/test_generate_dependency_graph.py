import sys
import tempfile
import unittest
from pathlib import Path


BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

from generate_dependency_graph import get_module_dependencies, get_untracked_dependencies
from module_utils import Version


class GenerateDependencyGraphTest(unittest.TestCase):

    def write_module(self, module_dir):
        module_dir.mkdir(parents=True)
        (module_dir / "MODULE.bazel").write_text(
            'module(name = "roo_consumer", version = "1.0.0")\n'
            'bazel_dep(name = "roo_runtime", version = "2.0.0")\n'
            'bazel_dep(name = "roo_dev", version = "3.0.0", '
            'dev_dependency = True)\n',
            encoding="utf-8",
        )

    def test_registered_module_ignores_dev_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            modules_dir = Path(temp_dir) / "modules"
            self.write_module(modules_dir / "roo_consumer" / "1.0.0")

            dependencies = get_module_dependencies(
                modules_dir, "roo_consumer", Version("1.0.0")
            )

        self.assertEqual(["roo_runtime"], [dep.name for dep in dependencies])

    def test_untracked_module_ignores_dev_dependencies(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry_dir = Path(temp_dir) / "roo-registry"
            registry_dir.mkdir()
            self.write_module(Path(temp_dir) / "roo_consumer")

            dependencies = get_untracked_dependencies(
                registry_dir, {"roo_consumer": Version("1.0.0")}
            )

        self.assertEqual(
            ["roo_runtime"], [dep.name for dep in dependencies["roo_consumer"]]
        )


if __name__ == "__main__":
    unittest.main()
