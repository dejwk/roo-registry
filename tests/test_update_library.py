import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

from module_utils import Dependency
from update_library import (
    create_argument_parser,
    get_latest_versions_from_registry,
    get_missing_registry_dependencies,
    update_library_files,
    update_module_bazel,
)


class UpdateLibraryTest(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_dir = Path(self.temp_dir.name)
        self.registry_dir = self.base_dir / "roo-registry"
        (self.registry_dir / "modules").mkdir(parents=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    def add_registry_version(self, name, version):
        version_dir = self.registry_dir / "modules" / name / version
        version_dir.mkdir(parents=True)
        (version_dir / "MODULE.bazel").write_text(
            f'module(name = "{name}", version = "{version}")\n',
            encoding="utf-8",
        )
        (version_dir / "source.json").write_text("{}\n", encoding="utf-8")

    def add_module(self, dependency_version="1.2.3", extra_dependencies=""):
        module_dir = self.base_dir / "roo_consumer"
        module_dir.mkdir()
        (module_dir / "MODULE.bazel").write_text(
            """module(
    name = "roo_consumer",
    version = "4.5.6",
)

bazel_dep(
    name = "roo_dep",
    version = "%s",
)
%s""" % (dependency_version, extra_dependencies),
            encoding="utf-8",
        )
        (module_dir / "library.json").write_text(
            json.dumps({"name": "roo_consumer", "version": "0.0.1"}) + "\n",
            encoding="utf-8",
        )
        (module_dir / "library.properties").write_text(
            "name=roo_consumer\nversion=0.0.1\ndepends=roo_old\n",
            encoding="utf-8",
        )
        return module_dir

    def update(self, latest_deps):
        with redirect_stdout(StringIO()):
            return update_library_files(
                "roo_consumer",
                latest_deps=latest_deps,
                registry_dir=self.registry_dir,
                base_dir=self.base_dir,
            )

    def test_cli_defaults_to_latest_and_accepts_no_latest_aliases(self):
        parser = create_argument_parser()

        self.assertFalse(parser.parse_args(["roo_consumer"]).nolatest_deps)
        self.assertTrue(
            parser.parse_args(
                ["roo_consumer", "--nolatest_deps"]
            ).nolatest_deps
        )
        self.assertTrue(
            parser.parse_args(
                ["roo_consumer", "--no-latest-deps"]
            ).nolatest_deps
        )

    def test_latest_updates_module_and_metadata(self):
        self.add_registry_version("roo_dep", "1.2.3")
        self.add_registry_version("roo_dep", "2.0.0")
        module_dir = self.add_module()

        self.assertTrue(self.update(latest_deps=True))

        module_content = (module_dir / "MODULE.bazel").read_text(encoding="utf-8")
        self.assertIn('version = "2.0.0",', module_content)
        metadata = json.loads((module_dir / "library.json").read_text())
        self.assertEqual("4.5.6", metadata["version"])
        self.assertEqual({"dejwk/roo_dep": ">=2.0.0"}, metadata["dependencies"])
        properties = (module_dir / "library.properties").read_text()
        self.assertIn("version=4.5.6\n", properties)
        self.assertIn("depends=roo_dep\n", properties)

    def test_no_latest_preserves_registered_nonlatest_pin_and_syncs_metadata(self):
        self.add_registry_version("roo_dep", "1.2.3")
        self.add_registry_version("roo_dep", "2.0.0")
        module_dir = self.add_module()
        original_module = (module_dir / "MODULE.bazel").read_bytes()

        self.assertTrue(self.update(latest_deps=False))

        self.assertEqual(original_module, (module_dir / "MODULE.bazel").read_bytes())
        metadata = json.loads((module_dir / "library.json").read_text())
        self.assertEqual({"dejwk/roo_dep": ">=1.2.3"}, metadata["dependencies"])
        self.assertIn(
            "depends=roo_dep\n",
            (module_dir / "library.properties").read_text(),
        )

    def test_no_latest_rejects_missing_exact_version_before_writes(self):
        self.add_registry_version("roo_dep", "2.0.0")
        module_dir = self.add_module()
        snapshots = {path.name: path.read_bytes() for path in module_dir.iterdir()}

        self.assertFalse(self.update(latest_deps=False))

        self.assertEqual(
            snapshots,
            {path.name: path.read_bytes() for path in module_dir.iterdir()},
        )

    def test_no_latest_rejects_invalid_roo_dependency_before_writes(self):
        module_dir = self.add_module(dependency_version="not-a-version")
        snapshots = {path.name: path.read_bytes() for path in module_dir.iterdir()}

        self.assertFalse(self.update(latest_deps=False))

        self.assertEqual(
            snapshots,
            {path.name: path.read_bytes() for path in module_dir.iterdir()},
        )

    def test_no_latest_ignores_external_dependencies(self):
        self.add_registry_version("roo_dep", "1.2.3")
        self.add_module(
            extra_dependencies=(
                'bazel_dep(name = "rules_cc", version = "0.2.17")\n'
            )
        )

        self.assertTrue(self.update(latest_deps=False))

    def test_no_latest_validates_roo_testing(self):
        dependencies = [Dependency("roo_testing", "2.0.0")]

        self.assertEqual(
            ["roo_testing@2.0.0"],
            [
                str(dep)
                for dep in get_missing_registry_dependencies(
                    dependencies,
                    self.registry_dir,
                )
            ],
        )

        self.add_registry_version("roo_testing", "2.0.0")
        self.assertEqual(
            [],
            get_missing_registry_dependencies(dependencies, self.registry_dir),
        )

    def test_skip_dev_dependencies_excludes_them_from_registry_metadata(self):
        self.add_registry_version("roo_dep", "1.2.3")
        self.add_registry_version("roo_dev", "4.5.6")
        module_dir = self.add_module(
            extra_dependencies=(
                'bazel_dep(name = "roo_dev", version = "4.5.6", '
                'dev_dependency = True)\n'
            )
        )

        with redirect_stdout(StringIO()):
            self.assertTrue(
                update_library_files(
                    "roo_consumer",
                    latest_deps=False,
                    skip_dev_dependencies=True,
                    registry_dir=self.registry_dir,
                    base_dir=self.base_dir,
                )
            )

        metadata = json.loads((module_dir / "library.json").read_text())
        self.assertEqual({"dejwk/roo_dep": ">=1.2.3"}, metadata["dependencies"])
        self.assertIn(
            "depends=roo_dep\n",
            (module_dir / "library.properties").read_text(),
        )

    def test_dependency_update_preserves_multiline_formatting(self):
        module_dir = self.add_module()
        module_path = module_dir / "MODULE.bazel"
        original = module_path.read_text(encoding="utf-8")

        self.assertTrue(
            update_module_bazel(module_path, [Dependency("roo_dep", "2.0.0")])
        )

        self.assertEqual(original.replace("1.2.3", "2.0.0"), module_path.read_text())

    def test_latest_ignores_incomplete_registry_versions(self):
        self.add_registry_version("roo_dep", "2.0.0")
        (self.registry_dir / "modules" / "roo_dep" / "3.0.0").mkdir()

        latest = get_latest_versions_from_registry(self.registry_dir)

        self.assertEqual("2.0.0", str(latest["roo_dep"]))


if __name__ == "__main__":
    unittest.main()
