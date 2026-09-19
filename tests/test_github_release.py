import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


BIN_DIR = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN_DIR))

import github_release
from release_notes import upsert_draft_entry


class GithubReleaseTest(unittest.TestCase):

    def test_create_release_targets_the_verified_commit_sha(self):
        result = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(
            github_release, "run_command", return_value=result
        ) as run:
            self.assertTrue(
                github_release.create_release(
                    Path("module"),
                    "owner/repo",
                    "roo_library",
                    "1.2.3",
                    "abc123",
                    "Release notes.",
                )
            )
        command = run.call_args.args[0]
        self.assertEqual("abc123", command[command.index("--target") + 1])
        self.assertEqual(
            "roo_library 1.2.3", command[command.index("--title") + 1]
        )

    def test_missing_command_returns_an_error_result_without_a_traceback(self):
        with (
            mock.patch.object(
                github_release.subprocess,
                "run",
                side_effect=FileNotFoundError(),
            ),
            contextlib.redirect_stderr(io.StringIO()) as errors,
        ):
            result = github_release.run_command(
                ["gh", "auth", "status"], Path("unused"), check=True
            )
        self.assertEqual(127, result.returncode)
        self.assertIn("Required command not found on PATH: gh", errors.getvalue())

    def test_notes_to_publish_reads_the_matching_top_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir)
            upsert_draft_entry(
                module_dir / "RELEASE_NOTES.md",
                "roo_library",
                "1.2.3",
                "- Fixed a release bug.",
            )
            with mock.patch.object(
                github_release,
                "full_changelog_url",
                return_value="https://github.com/owner/repo/compare/1.2.2...1.2.3",
            ):
                notes = github_release.notes_to_publish(
                    module_dir, "roo_library", "1.2.3", "owner/repo"
                )
            self.assertEqual(
                "- Fixed a release bug.\n\n**Full Changelog**: "
                "https://github.com/owner/repo/compare/1.2.2...1.2.3",
                notes,
            )

    def test_notes_to_publish_rejects_a_missing_or_nonmatching_top_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_dir = Path(temp_dir)
            (module_dir / "RELEASE_NOTES.md").write_text(
                "# roo_library 1.2.2\n\nOld notes.\n",
                encoding="utf-8",
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertIsNone(
                    github_release.notes_to_publish(
                        module_dir, "roo_library", "1.2.3", "owner/repo"
                    )
                )

    def test_github_repository_accepts_ssh_and_https_remotes(self):
        def ssh_command(command, *_args, **_kwargs):
            return subprocess.CompletedProcess(
                command, 0, "git@github.com:dejwk/roo_logging.git\n", ""
            )

        with mock.patch.object(github_release, "run_command", side_effect=ssh_command):
            self.assertEqual(
                "dejwk/roo_logging",
                github_release.github_repository(Path("unused")),
            )

        def https_command(command, *_args, **_kwargs):
            return subprocess.CompletedProcess(
                command, 0, "https://github.com/dejwk/roo_logging.git\n", ""
            )

        with mock.patch.object(
            github_release, "run_command", side_effect=https_command
        ):
            self.assertEqual(
                "dejwk/roo_logging",
                github_release.github_repository(Path("unused")),
            )

    def test_wait_for_ci_retries_until_a_successful_completed_run(self):
        responses = iter(
            [
                {},
                {"status": "in_progress", "url": "https://example/run"},
                {
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://example/run",
                },
            ]
        )
        with (
            mock.patch.object(github_release, "find_ci_run", side_effect=responses),
            mock.patch.object(github_release.time, "sleep") as sleep,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertTrue(
                github_release.wait_for_ci(Path("unused"), "owner/repo", "1.2.3")
            )
        self.assertEqual(2, sleep.call_count)

    def test_wait_for_ci_reports_a_failed_completed_run(self):
        with (
            mock.patch.object(
                github_release,
                "find_ci_run",
                return_value={
                    "status": "completed",
                    "conclusion": "failure",
                    "url": "url",
                },
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(
                github_release.wait_for_ci(Path("unused"), "owner/repo", "1.2.3")
            )

    def test_release_declined_after_ci_does_not_run_post_release(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            base = Path(temp_dir)
            registry = base / "roo-registry"
            module = base / "roo_library"
            (registry / "bin").mkdir(parents=True)
            module.mkdir()
            (module / "MODULE.bazel").write_text(
                'module(name = "roo_library", version = "1.2.3")\n',
                encoding="utf-8",
            )
            upsert_draft_entry(
                module / "RELEASE_NOTES.md",
                "roo_library",
                "1.2.3",
                "- Prepared notes.",
            )
            fake_script = registry / "bin" / "github_release.py"
            with (
                mock.patch.object(github_release, "__file__", str(fake_script)),
                mock.patch.object(
                    github_release, "github_repository", return_value="owner/repo"
                ),
                mock.patch.object(github_release, "head_sha", return_value="abc123"),
                mock.patch("builtins.input", side_effect=["y", "n"]),
                mock.patch.object(
                    github_release, "verify_prerequisites", return_value=True
                ),
                mock.patch.object(github_release, "create_release", return_value=True),
                mock.patch.object(github_release, "wait_for_ci", return_value=True),
                mock.patch.object(github_release, "run_post_release") as post_release,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertTrue(github_release.create_github_release("roo_library"))
            post_release.assert_not_called()

    def test_post_release_is_run_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Path(temp_dir)
            post_release = registry / "bin" / "post_release.py"
            post_release.parent.mkdir(parents=True)
            post_release.touch()
            with mock.patch.object(
                github_release.subprocess,
                "run",
                return_value=subprocess.CompletedProcess([], 0),
            ) as command, contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertTrue(
                    github_release.run_post_release(registry, "roo_library")
                )
            self.assertEqual(
                [sys.executable, str(post_release), "roo_library"],
                command.call_args.args[0],
            )
            self.assertNotIn("capture_output", command.call_args.kwargs)
            self.assertEqual(registry, command.call_args.kwargs["cwd"])
            self.assertIn("Running post-release actions", output.getvalue())


if __name__ == "__main__":
    unittest.main()
