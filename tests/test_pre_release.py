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
    is_version_published,
    propose_release_notes_with_codex,
    resolve_release_notes,
    run_bazel_tests,
    suggest_bump_type_with_codex,
    unchanged_since_latest_published_version,
    update_roo_testing_examples,
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

    def test_notes_are_accepted_on_the_command_line(self):
        args = self.parse("--patch", "--notes", "Fix the display driver.")
        self.assertEqual("Fix the display driver.", args.notes)

    def test_codex_proposal_is_printed_without_prompting(self):
        result = subprocess.CompletedProcess([], 0, "- Fixed a bug.\n", "")
        with (
            mock.patch.object(
                pre_release_module, "find_codex_executable", return_value="codex"
            ),
            mock.patch.object(pre_release_module, "run_command", return_value=result) as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(
                "- Fixed a bug.",
                propose_release_notes_with_codex(Path("/module"), "1.2.3"),
            )
        self.assertIn("Proposed release notes", output.getvalue())
        self.assertIn("Generating release notes with Codex", output.getvalue())
        command = run.call_args.args[0]
        self.assertEqual(["codex", "exec", "--ephemeral", "--sandbox", "read-only"], command[:5])

    def test_missing_codex_returns_a_clear_error_without_running_a_command(self):
        with (
            mock.patch.object(
                pre_release_module, "find_codex_executable", return_value=None
            ),
            mock.patch.object(pre_release_module, "run_command") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertIsNone(
                propose_release_notes_with_codex(Path("/module"), "1.2.3")
            )
        self.assertIn("Codex CLI was not found", output.getvalue())
        run.assert_not_called()

    def test_version_mode_is_optional_and_mutually_exclusive(self):
        self.assertIsNone(self.parse().bump_type)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as conflicting:
                self.parse("--current", "--patch")

        self.assertEqual(2, conflicting.exception.code)

    def test_existing_notes_are_kept_unless_regeneration_is_confirmed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir)
            (module_dir / "RELEASE_NOTES.md").write_text(
                "# roo_consumer 1.2.3\n\n- Existing notes.\n\n---\n",
                encoding="utf-8",
            )
            with (
                mock.patch("builtins.input", return_value="n") as ask,
                mock.patch.object(
                    pre_release_module, "propose_release_notes_with_codex"
                ) as propose,
            ):
                notes = resolve_release_notes(
                    module_dir, "roo_consumer", "1.2.3", None
                )

        self.assertEqual("- Existing notes.", notes)
        ask.assert_called_once()
        propose.assert_not_called()

    def test_existing_notes_are_regenerated_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir)
            (module_dir / "RELEASE_NOTES.md").write_text(
                "# roo_consumer 1.2.3\n\n- Existing notes.\n\n---\n",
                encoding="utf-8",
            )
            with (
                mock.patch("builtins.input", return_value="y"),
                mock.patch.object(
                    pre_release_module,
                    "propose_release_notes_with_codex",
                    return_value="- New notes.",
                ) as propose,
            ):
                notes = resolve_release_notes(
                    module_dir, "roo_consumer", "1.2.3", None
                )

        self.assertEqual("- New notes.", notes)
        propose.assert_called_once_with(module_dir, "1.2.3")

    def test_codex_recommends_a_semantic_version_action(self):
        result = subprocess.CompletedProcess([], 0, "minor\n", "")
        with (
            mock.patch.object(
                pre_release_module, "find_codex_executable", return_value="codex"
            ),
            mock.patch.object(pre_release_module, "run_command", return_value=result),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            recommendation = suggest_bump_type_with_codex(
                Path("/module"), "1.2.3", "- Added a substantial feature."
            )
        self.assertEqual("minor", recommendation)

    def test_release_type_confirmation_accepts_or_overrides_suggestion(self):
        for response, expected in (
            ("", "minor"), ("A", "major"), ("i", "minor"),
            ("P", "patch"), ("c", "current"), (" MAJOR ", "major"),
            ("minor", "minor"), ("patch", "patch"), ("current", "current"),
        ):
            with self.subTest(response=response), mock.patch("builtins.input", return_value=response):
                self.assertEqual(expected, pre_release_module.confirm_bump_type("minor"))

    def test_release_type_confirmation_reprompts_for_invalid_input(self):
        with (
            mock.patch("builtins.input", side_effect=["m", "y", "P"]) as ask,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertEqual("patch", pre_release_module.confirm_bump_type("minor"))
        self.assertEqual(3, ask.call_count)

    def test_automatic_release_uses_confirmed_type_before_resolving_notes(self):
        temp_dir, _base_dir, registry_dir, module_dir = self.make_release_fixture()
        self.addCleanup(temp_dir.cleanup)
        with (
            mock.patch.object(pre_release_module, "__file__", str(registry_dir / "bin" / "pre_release.py")),
            mock.patch.object(pre_release_module, "check_git_status", return_value=True),
            mock.patch.object(pre_release_module, "is_version_published", return_value=True),
            mock.patch.object(pre_release_module, "suggest_bump_type_with_codex", return_value="minor") as suggest,
            mock.patch("builtins.input", return_value="C") as ask,
            mock.patch.object(pre_release_module, "resolve_release_notes", return_value=None) as resolve,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(pre_release_module.pre_release(
                "roo_consumer", None, skip_tests=True, latest_deps=False,
                notes="- Dependency upgrades.",
            ))
        suggest.assert_called_once_with(module_dir, "4.5.6", "- Dependency upgrades.")
        ask.assert_called_once()
        self.assertIn("m[A]jor, m[I]nor, [P]atch, [C]urrent", ask.call_args.args[0])
        resolve.assert_called_once_with(module_dir, "roo_consumer", "4.5.6", "- Dependency upgrades.")

    def test_version_tag_marks_the_current_version_as_published(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir)
            subprocess.run(
                ["git", "init", "--initial-branch=main", str(module_dir)],
                check=True,
                capture_output=True,
            )
            (module_dir / "README.md").write_text("fixture\n", encoding="utf-8")
            subprocess.run(
                [
                    "git", "-C", str(module_dir), "-c", "user.name=Release Test",
                    "-c", "user.email=release-test@example.invalid", "add", ".",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git", "-C", str(module_dir), "-c", "user.name=Release Test",
                    "-c", "user.email=release-test@example.invalid", "commit",
                    "-m", "Initial",
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "-C", str(module_dir), "tag", "1.2.3"],
                check=True,
                capture_output=True,
            )
            self.assertTrue(is_version_published(module_dir, "1.2.3"))
            self.assertFalse(is_version_published(module_dir, "1.2.4"))

    def test_unchanged_tree_is_detected_from_the_latest_version_tag(self):
        temp_dir, _base_dir, _registry_dir, module_dir = self.make_release_fixture()
        self.addCleanup(temp_dir.cleanup)
        repo = git.Repo(module_dir)
        repo.create_tag("4.5.6")
        repo.create_tag("not-a-version")

        self.assertEqual(
            "4.5.6", unchanged_since_latest_published_version(module_dir)
        )

        (module_dir / "README.md").write_text("new behavior\n", encoding="utf-8")
        repo.index.add(["README.md"])
        repo.index.commit("Add behavior")
        self.assertIsNone(unchanged_since_latest_published_version(module_dir))

    def test_declining_unchanged_release_makes_no_git_changes(self):
        temp_dir, _base_dir, registry_dir, module_dir = self.make_release_fixture()
        self.addCleanup(temp_dir.cleanup)
        repo = git.Repo(module_dir)
        repo.create_tag("4.5.6")
        original_head = repo.head.commit.hexsha
        original_module = (module_dir / "MODULE.bazel").read_bytes()
        fake_script = registry_dir / "bin" / "pre_release.py"

        with (
            mock.patch.object(pre_release_module, "__file__", str(fake_script)),
            mock.patch.object(
                pre_release_module, "check_git_status", return_value=True
            ),
            mock.patch.object(
                pre_release_module, "propose_release_notes_with_codex"
            ) as propose,
            mock.patch("builtins.input", return_value="n") as confirm,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            success = pre_release_module.pre_release(
                "roo_consumer", "patch", skip_tests=True
            )

        self.assertFalse(success)
        confirm.assert_called_once_with(
            "No changes were detected since published version 4.5.6. "
            "Proceed with release preparation anyway? [y/N] "
        )
        propose.assert_not_called()
        self.assertEqual(original_head, repo.head.commit.hexsha)
        self.assertEqual(
            original_module, (module_dir / "MODULE.bazel").read_bytes()
        )
        self.assertFalse(repo.is_dirty(untracked_files=True))
        self.assertIn("Aborted without changing", output.getvalue())

    def test_current_preserves_version(self):
        self.assertEqual("4.5.6", increment_version("4.5.6", "current"))

    def test_no_latest_is_forwarded_to_metadata_synchronizer(self):
        script = Path("update_library.py")
        default_command = build_update_library_command(script, "roo_consumer", True)
        pinned_command = build_update_library_command(script, "roo_consumer", False)

        self.assertNotIn("--nolatest_deps", default_command)
        self.assertIn("--skip-dev-dependencies", default_command)
        self.assertIn("--skip-dev-dependencies", pinned_command)
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

    def test_roo_testing_example_versions_are_updated_without_other_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir)
            example_module = module_dir / "examples" / "simple" / "MODULE.bazel"
            example_module.parent.mkdir(parents=True)
            example_module.write_text(
                'bazel_dep(name = "rules_cc", version = "0.2.17")\n'
                'bazel_dep(name = "roo_testing", version = "2.0.1")\n',
                encoding="utf-8",
            )

            updated = update_roo_testing_examples(module_dir, "2.0.2")

            self.assertEqual([example_module], updated)
            self.assertEqual(
                'bazel_dep(name = "rules_cc", version = "0.2.17")\n'
                'bazel_dep(name = "roo_testing", version = "2.0.2")\n',
                example_module.read_text(encoding="utf-8"),
            )

    def test_roo_testing_uses_the_root_all_test_target(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir) / "roo_testing"
            module_dir.mkdir()

            with (
                mock.patch.object(pre_release_module.os.path, "exists", return_value=False),
                mock.patch.object(
                    pre_release_module.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess([], 0),
                ) as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertTrue(run_bazel_tests(module_dir))

            self.assertEqual(["bazel", "test", ":all"], run.call_args_list[0].args[0])

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

        # Use the files ref format because the installed GitPython cannot read
        # this environment's default reftable format.
        subprocess.run(
            ["git", "init", "--initial-branch=main", "--ref-format=files", str(module_dir)],
            check=True,
        )
        repo = git.Repo(module_dir)
        subprocess.run(
            [
                "git", "-C", str(module_dir), "-c", "user.name=Release Test",
                "-c", "user.email=release-test@example.invalid", "add", ".",
            ],
            check=True,
        )
        subprocess.run(
            [
                "git", "-C", str(module_dir), "-c", "user.name=Release Test",
                "-c", "user.email=release-test@example.invalid", "commit", "-m", "Initial",
            ],
            check=True,
        )
        return temp_dir, base_dir, registry_dir, module_dir

    def test_dependency_upgrades_precede_release_note_generation(self):
        for mode in (None, "current", "patch"):
            with self.subTest(mode=mode):
                temp_dir, base_dir, registry_dir, module_dir = self.make_release_fixture()
                self.addCleanup(temp_dir.cleanup)
                latest_dir = registry_dir / "modules" / "roo_dep" / "2.0.0"
                latest_dir.mkdir()
                (latest_dir / "MODULE.bazel").write_text(
                    'module(name = "roo_dep", version = "2.0.0")\n'
                )
                (latest_dir / "source.json").write_text("{}\n")

                def run_metadata(command, **kwargs):
                    self.assertEqual("update_library.py", Path(command[1]).name)
                    self.assertNotIn("--nolatest_deps", command)
                    success = update_library_files(
                        "roo_consumer", registry_dir=registry_dir, base_dir=base_dir
                    )
                    return subprocess.CompletedProcess(command, 0 if success else 1)

                def propose(module, version):
                    self.assertIn(
                        'bazel_dep(name = "roo_dep", version = "2.0.0")',
                        (module / "MODULE.bazel").read_text(),
                    )
                    # Stop before staging or publishing the fixture release.
                    return None

                with (
                    mock.patch.object(pre_release_module, "__file__", str(registry_dir / "bin" / "pre_release.py")),
                    mock.patch.object(pre_release_module, "check_git_status", return_value=True),
                    mock.patch.object(pre_release_module, "is_version_published", return_value=True),
                    mock.patch.object(pre_release_module.subprocess, "run", side_effect=run_metadata) as run,
                    mock.patch.object(pre_release_module, "propose_release_notes_with_codex", side_effect=propose) as notes,
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertFalse(pre_release_module.pre_release("roo_consumer", mode, skip_tests=True))
                run.assert_called_once()
                notes.assert_called_once()

    def test_failed_dependency_upgrade_stops_before_release_notes(self):
        temp_dir, _base_dir, registry_dir, module_dir = self.make_release_fixture()
        self.addCleanup(temp_dir.cleanup)
        original_module = (module_dir / "MODULE.bazel").read_bytes()
        with (
            mock.patch.object(pre_release_module, "__file__", str(registry_dir / "bin" / "pre_release.py")),
            mock.patch.object(pre_release_module, "check_git_status", return_value=True),
            mock.patch.object(pre_release_module.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)),
            mock.patch.object(pre_release_module, "propose_release_notes_with_codex") as notes,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(pre_release_module.pre_release("roo_consumer", "patch", skip_tests=True))
        notes.assert_not_called()
        self.assertEqual(original_module, (module_dir / "MODULE.bazel").read_bytes())
        self.assertFalse((module_dir / "RELEASE_NOTES.md").exists())

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
                    mock.patch("builtins.input", return_value="y") as confirm,
                    contextlib.redirect_stdout(io.StringIO()) as output,
                ):
                    success = pre_release_module.pre_release(
                        "roo_consumer",
                        mode,
                        skip_tests=True,
                        latest_deps=False,
                        notes="- Prepared release notes.",
                    )

                self.assertTrue(success)
                confirm.assert_called_once_with("\nContinue with commit and push? [y/N] ")
                self.assertIn("Git changes ready for release", output.getvalue())
                self.assertLess(
                    output.getvalue().index("Git changes ready for release"),
                    output.getvalue().index("Release notes to commit and publish"),
                )
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
                self.assertTrue(
                    (module_dir / "RELEASE_NOTES.md").read_text().startswith(
                        f"# roo_consumer {expected_version}\n\n- Prepared release notes."
                    )
                )


if __name__ == "__main__":
    unittest.main()
