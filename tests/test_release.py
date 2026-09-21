import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bin"))

import release
import github_release
import pre_release


class ReleaseTest(unittest.TestCase):
    def run_workflow(self, outcomes=(True, True, True), answer="y"):
        args = release.create_argument_parser().parse_args([
            "roo_library", "--current", "--nolatest_deps", "--skip-tests",
            "--skip-publish", "--notes", "Prepared notes.",
        ])
        calls = mock.Mock()
        with (
            mock.patch.object(release.pre_release, "pre_release", return_value=outcomes[0]) as pre,
            mock.patch.object(release.github_release, "create_github_release", return_value=outcomes[1]) as github,
            mock.patch.object(release.post_release, "post_release", return_value=outcomes[2]) as post,
            mock.patch("builtins.input", return_value=answer) as ask,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            calls.attach_mock(pre, "pre")
            calls.attach_mock(github, "github")
            calls.attach_mock(ask, "ask")
            calls.attach_mock(post, "post")
            success = release.release(args)
        return success, calls, output.getvalue()

    def test_stages_run_in_order_and_preserve_options(self):
        success, calls, output = self.run_workflow()
        self.assertTrue(success)
        self.assertEqual([
            mock.call.pre("roo_library", "current", skip_tests=True,
                          latest_deps=False, notes="Prepared notes.", review_diff=True),
            mock.call.github("roo_library", offer_post_release=False),
            mock.call.ask("Proceed with post-release actions? [y/N] "),
            mock.call.post("roo_library", skip_publish=True),
        ], calls.mock_calls)
        self.assertIn("CI passed", output)
        self.assertIn("Release workflow completed", output)

    def test_each_failed_stage_stops_later_stages(self):
        for outcomes, expected in (
            ((False, True, True), ["pre"]),
            ((True, False, True), ["pre", "github"]),
            ((True, True, False), ["pre", "github", "ask", "post"]),
        ):
            with self.subTest(outcomes=outcomes):
                success, calls, output = self.run_workflow(outcomes)
                self.assertFalse(success)
                self.assertEqual(expected, [call[0] for call in calls.mock_calls])
                self.assertNotIn("Release workflow completed", output)

    def test_declining_post_release_prints_resume_command(self):
        success, calls, output = self.run_workflow(answer="")
        self.assertFalse(success)
        calls.post.assert_not_called()
        self.assertIn("post_release.py roo_library --skip-publish", output)

    def test_default_options_match_pre_release(self):
        args = release.create_argument_parser().parse_args(["roo_library"])
        self.assertIsNone(args.bump_type)
        self.assertFalse(args.skip_tests)
        self.assertFalse(args.nolatest_deps)
        self.assertFalse(args.skip_publish)

    def test_interruption_and_eof_return_failure(self):
        for error in (EOFError, KeyboardInterrupt):
            with (
                self.subTest(error=error),
                mock.patch.object(sys, "argv", ["release.py", "roo_library"]),
                mock.patch.object(release, "release", side_effect=error),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(1, release.main())
                self.assertIn("not been rolled back", output.getvalue())


class DiffReviewTest(unittest.TestCase):
    def test_tig_pager_receives_staged_patch_and_inherits_terminal_output(self):
        patch = "diff --git a/file b/file\n--- a/file\n+++ b/file\n"
        with (
            mock.patch("builtins.input", return_value="y"),
            mock.patch.object(pre_release.subprocess, "run", side_effect=[
                subprocess.CompletedProcess([], 0, patch, ""),
                subprocess.CompletedProcess([], 0),
            ]) as run,
        ):
            self.assertTrue(pre_release.review_staged_diff(Path("module")))
        self.assertEqual([
            mock.call(["git", "diff", "--cached", "--no-color", "--no-ext-diff"],
                      cwd=Path("module"), capture_output=True, text=True),
            mock.call(["tig"], input=patch, cwd=Path("module"), text=True),
        ], run.call_args_list)

    def test_last_release_diff_includes_committed_and_staged_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Path(directory)
            subprocess.run(
                ["git", "init", "--initial-branch=main", "--ref-format=files", directory],
                check=True, capture_output=True,
            )
            repo = pre_release.git.Repo(module)
            actor = pre_release.git.Actor("Release Test", "test@example.com")

            def commit_file(name):
                (module / name).write_text(name + "\n")
                repo.index.add([name])
                return repo.index.commit(name, author=actor, committer=actor)

            initial = commit_file("initial")
            repo.create_tag("1.0.0")
            commit_file("previous_release")
            repo.create_tag("1.1.0")
            commit_file("committed_change")
            repo.create_tag("not-a-release")
            repo.create_head("other", initial).checkout()
            commit_file("unrelated_change")
            repo.create_tag("9.0.0")
            repo.heads.main.checkout()
            (module / "staged_change").write_text("staged change\n")
            repo.index.add(["staged_change"])
            (module / "unstaged_change").write_text("not included\n")
            real_run = subprocess.run
            patches = []

            def run(command, **kwargs):
                if command == ["tig"]:
                    patches.append(kwargs["input"])
                    return subprocess.CompletedProcess(command, 0)
                return real_run(command, **kwargs)

            with (
                mock.patch("builtins.input", return_value="l"),
                mock.patch.object(pre_release.subprocess, "run", side_effect=run),
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                self.assertTrue(pre_release.review_staged_diff(module))
            self.assertIn("since release 1.1.0", output.getvalue())
            self.assertEqual(1, len(patches))
            self.assertIn("committed_change", patches[0])
            self.assertIn("staged_change", patches[0])
            self.assertNotIn("previous_release", patches[0])
            self.assertNotIn("unrelated_change", patches[0])
            self.assertNotIn("unstaged_change", patches[0])

    def test_last_release_review_without_tag_stops_before_approval(self):
        with (
            mock.patch("builtins.input", return_value="l"),
            mock.patch.object(pre_release.git, "Repo"),
            mock.patch.object(pre_release, "latest_published_tag", return_value=None),
            mock.patch.object(pre_release.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertFalse(pre_release.review_staged_diff(Path("module")))
        run.assert_not_called()
        self.assertIn("No reachable release-version tag", output.getvalue())

    def test_invalid_review_choice_is_reprompted(self):
        with (
            mock.patch("builtins.input", side_effect=["invalid", "n"]) as ask,
            mock.patch.object(pre_release.subprocess, "run") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertTrue(pre_release.review_staged_diff(Path("module")))
        self.assertEqual(2, ask.call_count)
        run.assert_not_called()

    def test_declining_optional_review_allows_approval(self):
        with mock.patch("builtins.input", return_value=""), mock.patch.object(pre_release.subprocess, "run") as run:
            self.assertTrue(pre_release.review_staged_diff(Path("module")))
        run.assert_not_called()

    def test_missing_or_failed_tig_stops_before_approval(self):
        for result in (FileNotFoundError("tig"), subprocess.CompletedProcess([], 1)):
            with (
                self.subTest(result=result),
                mock.patch("builtins.input", return_value="y"),
                mock.patch.object(pre_release.subprocess, "run", side_effect=[
                    subprocess.CompletedProcess([], 0, "staged patch", ""), result,
                ]),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertFalse(pre_release.review_staged_diff(Path("module")))

    def test_empty_or_failed_diff_does_not_open_tig(self):
        for code in (0, 1):
            with (
                self.subTest(code=code),
                mock.patch("builtins.input", return_value="y"),
                mock.patch.object(pre_release.subprocess, "run", return_value=
                                  subprocess.CompletedProcess([], code, "", "error")) as run,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(code == 0, pre_release.review_staged_diff(Path("module")))
                run.assert_called_once()


class PreReleaseReviewOrderTest(unittest.TestCase):
    def test_review_precedes_approval_and_failure_never_prompts_or_pushes(self):
        for reviewed in (True, False):
            with self.subTest(reviewed=reviewed), tempfile.TemporaryDirectory() as directory:
                registry = Path(directory) / "roo-registry"
                module = Path(directory) / "roo_testing"
                module.mkdir()
                (module / "MODULE.bazel").write_text(
                    'module(name="roo_testing", version="1.2.3")\n'
                )
                events = []
                repo = mock.Mock()

                def review(_module):
                    repo.index.add.assert_called()
                    events.append("review")
                    return reviewed

                def approve(_prompt):
                    events.append("approve")
                    return "n"

                with (
                    mock.patch.object(pre_release, "__file__", str(registry / "bin/pre_release.py")),
                    mock.patch.object(pre_release, "check_git_status", return_value=True),
                    mock.patch.object(pre_release, "unchanged_since_latest_published_version", return_value=None),
                    mock.patch.object(pre_release.git, "Repo", return_value=repo),
                    mock.patch.object(pre_release, "print_release_summary"),
                    mock.patch.object(pre_release, "review_staged_diff", side_effect=review),
                    mock.patch.object(pre_release, "git_push") as push,
                    mock.patch("builtins.input", side_effect=approve),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertFalse(pre_release.pre_release(
                        "roo_testing", "current", skip_tests=True,
                        notes="Prepared notes.", review_diff=True,
                    ))
                self.assertEqual(["review", "approve"] if reviewed else ["review"], events)
                repo.index.commit.assert_not_called()
                push.assert_not_called()


class GithubHandoffTest(unittest.TestCase):
    def test_wrapper_mode_prints_url_before_ci_without_post_release_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "roo-registry"
            module = Path(directory) / "roo_library"
            module.mkdir()
            with (
                mock.patch.object(github_release, "__file__", str(registry / "bin/github_release.py")),
                mock.patch.object(github_release, "get_module_version", return_value="1.2.3"),
                mock.patch.object(github_release, "github_repository", return_value="owner/repo"),
                mock.patch.object(github_release, "head_sha", return_value="abc123"),
                mock.patch.object(github_release, "verify_prerequisites", return_value=True),
                mock.patch.object(github_release, "notes_to_publish", return_value="Notes."),
                mock.patch.object(github_release, "create_release", return_value=True) as create,
                mock.patch.object(github_release, "run_post_release") as post,
                mock.patch("builtins.input", return_value="y") as ask,
                contextlib.redirect_stdout(io.StringIO()) as output,
            ):
                def wait(*_args, **kwargs):
                    if "commit_sha" in kwargs:
                        create.assert_not_called()
                        return True
                    create.assert_called_once()
                    self.assertEqual({"tag": "1.2.3"}, kwargs)
                    self.assertIn("https://github.com/owner/repo/releases/tag/1.2.3", output.getvalue())
                    return True

                with mock.patch.object(
                    github_release, "wait_for_ci", side_effect=wait
                ) as wait_for_ci:
                    self.assertTrue(github_release.create_github_release("roo_library", offer_post_release=False))
                ask.assert_called_once_with("Proceed? [y/N] ")
                post.assert_not_called()
                self.assertEqual(2, wait_for_ci.call_count)


if __name__ == "__main__":
    unittest.main()
