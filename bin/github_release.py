#!/usr/bin/env python3
"""Create a GitHub release for a prepared Roo library and wait for CI.

Usage: python3 roo-registry/bin/github_release.py <module_name>
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from module_utils import parse_module_bazel
from release_notes import read_top_entry

CI_WORKFLOW = "CI"
POLL_INTERVAL_SECONDS = 10


def run_command(
    command: list[str], cwd: Path, check: bool = False
) -> subprocess.CompletedProcess:
    """Run a command while preserving output for helpful error messages."""
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True)
    except FileNotFoundError:
        result = subprocess.CompletedProcess(
            command,
            127,
            "",
            f"Required command not found on PATH: {command[0]}\n",
        )
    if check and result.returncode:
        print(f"Error running: {' '.join(command)}")
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
    return result


def get_module_version(module_dir: Path) -> Optional[str]:
    """Return the release version declared by a module's MODULE.bazel."""
    module_bazel = module_dir / "MODULE.bazel"
    if not module_bazel.is_file():
        print(f"Error: MODULE.bazel not found in {module_dir}")
        return None
    try:
        _, version, _ = parse_module_bazel(module_bazel)
    except ValueError as error:
        print(f"Error parsing {module_bazel}: {error}")
        return None
    if not version:
        print(f"Error: no version declared in {module_bazel}")
    return version


def github_repository(module_dir: Path) -> Optional[str]:
    """Return the owner/repository name configured for origin."""
    result = run_command(
        ["git", "remote", "get-url", "origin"], module_dir, check=True
    )
    if result.returncode:
        return None
    remote = result.stdout.strip()
    if remote.startswith("git@github.com:"):
        remote = remote.removeprefix("git@github.com:")
    elif remote.startswith("https://github.com/"):
        remote = remote.removeprefix("https://github.com/")
    else:
        print(f"Error: origin is not a GitHub repository: {remote}")
        return None
    return remote.removesuffix(".git")


def head_sha(module_dir: Path) -> Optional[str]:
    """Return the commit that the release tag will point to."""
    result = run_command(["git", "rev-parse", "HEAD"], module_dir, check=True)
    return result.stdout.strip() if not result.returncode else None


def full_changelog_url(module_dir: Path, repository: str, tag: str) -> Optional[str]:
    """Build the GitHub comparison URL from the nearest previous local tag."""
    result = run_command(
        ["git", "describe", "--tags", "--abbrev=0", "HEAD"], module_dir
    )
    if result.returncode:
        print("Warning: no previous tag found; omitting the full changelog link.")
        return None
    previous_tag = result.stdout.strip()
    if not previous_tag or previous_tag == tag:
        return None
    return f"https://github.com/{repository}/compare/{previous_tag}...{tag}"


def notes_to_publish(module_dir: Path, module_name: str, version: str, repository: str) -> Optional[str]:
    """Read the prepared draft and append GitHub's full-changelog link."""
    notes = read_top_entry(module_dir / "RELEASE_NOTES.md", module_name, version)
    if notes is None:
        print(
            "Error: RELEASE_NOTES.md must start with a non-empty "
            f"'# {module_name} {version}' entry. Run pre_release.py first."
        )
        return None
    changelog_url = full_changelog_url(module_dir, repository, version)
    if changelog_url:
        notes = f"{notes.rstrip()}\n\n**Full Changelog**: {changelog_url}"
    return notes


def verify_prerequisites(module_dir: Path, repository: str, tag: str) -> bool:
    """Verify GitHub CLI access and ensure the tag does not already exist."""
    auth = run_command(["gh", "auth", "status"], module_dir, check=True)
    if auth.returncode:
        print("Install and authenticate the GitHub CLI before creating a release.")
        return False

    existing = run_command(
        ["gh", "release", "view", tag, "--repo", repository], module_dir
    )
    if existing.returncode == 0:
        print(f"Error: GitHub release {tag} already exists in {repository}")
        return False
    return True


def create_release(
    module_dir: Path,
    repository: str,
    module_name: str,
    tag: str,
    target_sha: str,
    notes: str,
) -> bool:
    """Create a named release and its version tag at the verified commit."""
    result = run_command(
        [
            "gh", "release", "create", tag,
            "--repo", repository,
            "--target", target_sha,
            "--title", f"{module_name} {tag}",
            "--notes", notes,
        ],
        module_dir,
        check=True,
    )
    return result.returncode == 0


def find_ci_run(module_dir: Path, repository: str, tag: str) -> Optional[dict]:
    """Find the CI workflow run caused by pushing this release tag."""
    result = run_command(
        [
            "gh", "run", "list",
            "--repo", repository,
            "--workflow", CI_WORKFLOW,
            "--branch", tag,
            "--event", "push",
            "--limit", "1",
            "--json", "databaseId,status,conclusion,url",
        ],
        module_dir,
    )
    if result.returncode:
        print("Error: could not query GitHub Actions runs")
        return None
    try:
        runs = json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Error: GitHub CLI returned invalid workflow data")
        return None
    return runs[0] if runs else {}


def wait_for_ci(module_dir: Path, repository: str, tag: str) -> bool:
    """Wait until the tag's CI run succeeds, or report its failure."""
    print(f"Waiting for the {CI_WORKFLOW} workflow for tag {tag} to start...")
    while True:
        run = find_ci_run(module_dir, repository, tag)
        if run is None:
            return False
        if not run:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        status = run["status"]
        url = run.get("url", "")
        if status != "completed":
            print(f"CI is {status}: {url}")
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        if run.get("conclusion") == "success":
            print(f"✓ CI is green: {url}")
            return True
        print(f"✗ CI finished with {run.get('conclusion')}: {url}")
        return False


def run_post_release(registry_dir: Path, module_name: str) -> bool:
    """Run the registry and PlatformIO publication steps after a green CI run."""
    post_release_script = registry_dir / "bin" / "post_release.py"
    if not post_release_script.is_file():
        print(f"Error: post_release.py not found at {post_release_script}")
        return False
    print("\nRunning post-release actions...\n")
    result = subprocess.run(
        [sys.executable, str(post_release_script), module_name],
        cwd=registry_dir,
        text=True,
    )
    if result.returncode:
        print(f"Error: post-release actions failed with exit code {result.returncode}.")
    return result.returncode == 0


def create_github_release(module_name: str) -> bool:
    """Interactively create a module release, then wait for its CI result."""
    registry_dir = Path(__file__).resolve().parent.parent
    module_dir = registry_dir.parent / module_name
    if not module_dir.is_dir():
        print(f"Error: module directory does not exist: {module_dir}")
        return False

    version = get_module_version(module_dir)
    repository = github_repository(module_dir)
    sha = head_sha(module_dir)
    if not version or not repository or not sha:
        return False

    tag = version
    if not verify_prerequisites(module_dir, repository, tag):
        return False

    notes = notes_to_publish(module_dir, module_name, version, repository)
    if notes is None:
        return False

    print("\nThe following actions will be performed:")
    print(f"  1. Create GitHub release {repository}@{tag} for commit {sha}.")
    print(f"  2. Publish release notes from RELEASE_NOTES.md:\n\n{notes}")
    print(f"  3. Wait for the {CI_WORKFLOW} workflow triggered by tag {tag} to succeed.")
    if input("Proceed? [y/N] ").strip().lower() != "y":
        print("Aborted by user.")
        return False

    if not create_release(module_dir, repository, module_name, tag, sha, notes):
        return False
    print(f"✓ Created GitHub release {repository}@{tag}")
    if not wait_for_ci(module_dir, repository, tag):
        return False

    if input("Run post-release actions now? [y/N] ").strip().lower() != "y":
        print("GitHub release complete; post-release actions were skipped.")
        return True
    return run_post_release(registry_dir, module_name)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create a Roo library release on GitHub and wait for CI"
    )
    parser.add_argument("module_name", help="Name of the module to release")
    args = parser.parse_args()
    sys.exit(0 if create_github_release(args.module_name) else 1)


if __name__ == "__main__":
    main()
