import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import git


BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

import pre_release as pre_release_module
from pre_release import (
    build_update_library_command,
    create_argument_parser,
    increment_version,
    update_module_bazel_version,
)
from update_library import update_library_files


class PreReleaseTest(unittest.TestCase):

    def parse(self, *arguments):
        return create_argument_parser().parse_args(["roo_consumer", *arguments])

    def test_all_version_modes_default_to_latest_dependencies(self):
        for flag, expected in (
            ("--major", "major"),
            ("--minor", "minor"),
            ("--patch", "patch"),
            ("--current", "current"),
        ):
            with self.subTest(flag=flag):
                args = self.parse(flag)
                self.assertEqual(expected, args.bump_type)
                self.assertFalse(args.nolatest_deps)

    def test_no_latest_combines_with_every_version_mode(self):
        for flag in ("--major", "--minor", "--patch", "--current"):
            with self.subTest(flag=flag):
                args = self.parse(flag, "--nolatest_deps")
                self.assertTrue(args.nolatest_deps)

    def test_version_mode_is_required_and_mutually_exclusive(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as missing:
                self.parse()
            with self.assertRaises(SystemExit) as conflicting:
                self.parse("--current", "--patch")

        self.assertEqual(2, missing.exception.code)
        self.assertEqual(2, conflicting.exception.code)

    def test_current_preserves_version(self):
        self.assertEqual("4.5.6", increment_version("4.5.6", "current"))

    def test_no_latest_is_forwarded_to_metadata_synchronizer(self):
        script = Path("update_library.py")
        default_command = build_update_library_command(script, "roo_consumer", True)
        pinned_command = build_update_library_command(script, "roo_consumer", False)

        self.assertNotIn("--nolatest_deps", default_command)
        self.assertEqual("--nolatest_deps", pinned_command[-1])

    def test_version_update_accepts_multiline_module_declaration(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_path = Path(temp_dir) / "MODULE.bazel"
            module_path.write_text(
                """module(
    name = "roo_consumer",
    version = "4.5.6",
)
""",
                encoding="utf-8",
            )

            self.assertTrue(update_module_bazel_version(module_path, "5.0.0"))
            self.assertIn(
                'version = "5.0.0",',
                module_path.read_text(encoding="utf-8"),
            )

    def make_release_fixture(self):
        temp_dir = tempfile.TemporaryDirectory()
        base_dir = Path(temp_dir.name)
        registry_dir = base_dir / "roo-registry"
        (registry_dir / "bin").mkdir(parents=True)
        dependency_dir = registry_dir / "modules" / "roo_dep" / "1.2.3"
        dependency_dir.mkdir(parents=True)
        (dependency_dir / "MODULE.bazel").write_text(
            'module(name = "roo_dep", version = "1.2.3")\n',
            encoding="utf-8",
        )
        (dependency_dir / "source.json").write_text("{}\n", encoding="utf-8")

        module_dir = base_dir / "roo_consumer"
        module_dir.mkdir()
        (module_dir / "MODULE.bazel").write_text(
            'module(name = "roo_consumer", version = "4.5.6")\n'
            'bazel_dep(name = "roo_dep", version = "1.2.3")\n',
            encoding="utf-8",
        )
        (module_dir / "library.json").write_text(
            '{"name": "roo_consumer", "version": "0.0.1"}\n',
            encoding="utf-8",
        )
        (module_dir / "library.properties").write_text(
            "name=roo_consumer\nversion=0.0.1\n",
            encoding="utf-8",
        )

        repo = git.Repo.init(module_dir)
        with repo.config_writer() as config:
            config.set_value("user", "name", "Release Test")
            config.set_value("user", "email", "release-test@example.invalid")
        repo.index.add(["MODULE.bazel", "library.json", "library.properties"])
        repo.index.commit("Initial")
        return temp_dir, base_dir, registry_dir, module_dir

    def test_no_latest_composes_with_current_and_major_release_modes(self):
        for mode, expected_version in (("current", "4.5.6"), ("major", "5.0.0")):
            with self.subTest(mode=mode):
                temp_dir, base_dir, registry_dir, module_dir = (
                    self.make_release_fixture()
                )
                self.addCleanup(temp_dir.cleanup)

                def run_metadata(command, **_kwargs):
                    success = update_library_files(
                        "roo_consumer",
                        latest_deps="--nolatest_deps" not in command,
                        registry_dir=registry_dir,
                        base_dir=base_dir,
                    )
                    return subprocess.CompletedProcess(
                        command,
                        0 if success else 1,
                    )

                fake_script = registry_dir / "bin" / "pre_release.py"
                with (
                    mock.patch.object(
                        pre_release_module,
                        "__file__",
                        str(fake_script),
                    ),
                    mock.patch.object(
                        pre_release_module,
                        "check_git_status",
                        return_value=True,
                    ),
                    mock.patch.object(
                        pre_release_module.subprocess,
                        "run",
                        side_effect=run_metadata,
                    ),
                    mock.patch.object(
                        pre_release_module,
                        "git_push",
                        return_value=(True, "pushed"),
                    ),
                    mock.patch("builtins.input", return_value="y"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    success = pre_release_module.pre_release(
                        "roo_consumer",
                        mode,
                        skip_tests=True,
                        latest_deps=False,
                    )

                self.assertTrue(success)
                module_content = (module_dir / "MODULE.bazel").read_text()
                self.assertIn(f'version = "{expected_version}"', module_content)
                self.assertIn(
                    'bazel_dep(name = "roo_dep", version = "1.2.3")',
                    module_content,
                )
                metadata = json.loads((module_dir / "library.json").read_text())
                self.assertEqual(expected_version, metadata["version"])
                self.assertEqual(
                    {"dejwk/roo_dep": ">=1.2.3"},
                    metadata["dependencies"],
                )
                self.assertIn(
                    f"version={expected_version}\n",
                    (module_dir / "library.properties").read_text(),
                )


if __name__ == "__main__":
    unittest.main()
