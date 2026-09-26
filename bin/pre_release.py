#!/usr/bin/env python3
"""
Script to prepare a module release using a selected version policy.

Usage: python3 roo-registry/bin/pre_release.py <module_name> [--major|--minor|--patch|--current] [--notes NOTES]

This script will:
1. Verify git status is clean and up-to-date with upstream
2. Copy template/push contents into the repository, overwriting matching files
3. Upgrade Roo dependencies to the latest registered versions
4. Select or increment the version number in MODULE.bazel
5. Create or update the top RELEASE_NOTES.md entry
6. Update library metadata and run bazel tests in a subprocess
7. Show and confirm the staged release, then commit and push it

Example: python3 roo-registry/bin/pre_release.py roo_display
"""

import sys
import os
import shutil
import subprocess
import argparse
import re
from pathlib import Path
from typing import List, Tuple, Optional

# Check for GitPython availability
try:
    import git
except ImportError:
    raise ImportError(
        "GitPython is required but not installed.\n"
        "Install it with: pip install GitPython"
    )

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import (
    Version, parse_module_bazel, get_git_status,
    has_remote_changes, count_commits_between, get_current_branch, 
    get_upstream_branch, git_push, replace_module_version,
)
from update_library import validate_registry_dependencies
from release_notes import read_top_entry, upsert_draft_entry


ROO_TESTING_MODULE = "roo_testing"


def run_command(cmd: list, cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"stdout: {result.stdout}")
        print(f"stderr: {result.stderr}")
        sys.exit(1)
    return result


def build_update_library_command(
    update_script: Path,
    module_name: str,
    latest_deps: bool,
) -> list:
    """Build the metadata synchronization command for a release."""
    command = [sys.executable, str(update_script), module_name]
    command.append("--skip-dev-dependencies")
    if not latest_deps:
        command.append("--nolatest_deps")
    return command


def find_codex_executable() -> Optional[str]:
    """Find Codex on PATH, through CODEX_BIN, or in a VS Code extension."""
    configured = os.environ.get("CODEX_BIN")
    if configured:
        configured_path = Path(configured).expanduser()
        if configured_path.is_file() and os.access(configured_path, os.X_OK):
            return str(configured_path)
        print(f"Warning: CODEX_BIN is not executable: {configured_path}")

    from_path = shutil.which("codex")
    if from_path:
        return from_path

    candidates = []
    for extensions_dir in (
        Path.home() / ".vscode" / "extensions",
        Path.home() / ".vscode-server" / "extensions",
    ):
        if extensions_dir.is_dir():
            candidates.extend(
                path for path in extensions_dir.glob("openai.chatgpt-*/bin/*/codex")
                if path.is_file() and os.access(path, os.X_OK)
            )
    return str(max(candidates, key=lambda path: path.stat().st_mtime)) if candidates else None


def propose_release_notes_with_codex(module_dir: Path, version: str) -> Optional[str]:
    """Ask Codex for a read-only proposed Markdown release-note body."""
    codex = find_codex_executable()
    if codex is None:
        print(
            "Error: Codex CLI was not found. Install Codex, set CODEX_BIN to its "
            "executable path, or provide release notes with --notes."
        )
        return None
    print("Generating release notes with Codex; this can take a while...")
    prompt = (
        f"Generate concise Markdown release notes for {module_dir.name} version "
        f"{version}. Review the changes since the most recent release tag in "
        "this repository, including uncommitted dependency upgrades in the working "
        "tree. Return only the release-note body: no title, date, "
        "preamble, full-changelog link, or horizontal rule."
    )
    try:
        result = run_command(
            [
                codex, "exec", "--ephemeral", "--sandbox", "read-only",
                "--cd", str(module_dir), prompt,
            ],
            cwd=module_dir,
            check=False,
        )
    except OSError as error:
        print(f"Error: could not start Codex ({error}). Use --notes to continue.")
        return None
    if result.returncode != 0:
        print("Error: Codex could not generate release notes.")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return None
    notes = result.stdout.strip()
    if not notes:
        print("Error: Codex returned empty release notes.")
        return None
    print("\nProposed release notes:\n")
    print(notes)
    return notes


def is_version_published(module_dir: Path, version: str) -> bool:
    """Return whether the version has a release tag in the fetched repository."""
    result = run_command(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/tags/{version}"],
        cwd=module_dir,
        check=False,
    )
    return result.returncode == 0


def latest_published_tag(repo: git.Repo) -> Optional[git.TagReference]:
    """Return the highest release-version tag reachable from HEAD."""
    version_tags = []
    for tag in repo.tags:
        try:
            version = Version(tag.name)
        except ValueError:
            continue
        if repo.is_ancestor(tag.commit, repo.head.commit):
            version_tags.append((version, tag))
    return max(version_tags, key=lambda item: item[0])[1] if version_tags else None


def unchanged_since_latest_published_version(module_dir: Path) -> Optional[str]:
    """Return the newest reachable version tag when its tree matches HEAD."""
    try:
        repo = git.Repo(module_dir)
        latest_tag = latest_published_tag(repo)
        if latest_tag is not None and latest_tag.commit.tree == repo.head.commit.tree:
            return latest_tag.name
    except (git.GitError, ValueError):
        pass
    return None


def suggest_bump_type_with_codex(
    module_dir: Path, current_version: str, notes: str
) -> Optional[str]:
    """Ask Codex to classify an unpublished change set by release impact."""
    codex = find_codex_executable()
    if codex is None:
        print(
            "Error: Codex CLI was not found. Install Codex, set CODEX_BIN to its "
            "executable path, or select --major, --minor, --patch, or --current."
        )
        return None
    print("Asking Codex to recommend the release version; this can take a while...")
    prompt = (
        f"Recommend the semantic-version action for {module_dir.name}, whose "
        f"current version is {current_version}. Review the repository changes "
        "since the most recent release tag, including uncommitted dependency "
        "upgrades in the working tree, and use these proposed release notes "
        f"as additional context:\n\n{notes}\n\n"
        "Choose major for breaking changes or major new functionality; minor "
        "for significant new functionality; patch only for bug fixes and minor "
        "tweaks. Return exactly one word: major, minor, or patch."
    )
    try:
        result = run_command(
            [
                codex, "exec", "--ephemeral", "--sandbox", "read-only",
                "--cd", str(module_dir), prompt,
            ],
            cwd=module_dir,
            check=False,
        )
    except OSError as error:
        print(f"Error: could not start Codex ({error}). Select a version flag to continue.")
        return None
    if result.returncode != 0:
        print("Error: Codex could not recommend a release version.")
        if result.stderr:
            print(result.stderr, end="", file=sys.stderr)
        return None
    recommendation = result.stdout.strip().lower()
    if recommendation not in {"major", "minor", "patch"}:
        print(
            "Error: Codex returned an invalid version recommendation: "
            f"{result.stdout.strip()!r}"
        )
        return None
    print(f"Codex recommends a {recommendation} release.")
    return recommendation



def confirm_bump_type(suggestion: str) -> str:
    """Let the user accept or override Codex's release-type recommendation."""
    choices = {
        "a": "major", "major": "major",
        "i": "minor", "minor": "minor",
        "p": "patch", "patch": "patch",
        "c": "current", "current": "current",
    }
    while True:
        response = input(
            "Release type: m[A]jor, m[I]nor, [P]atch, [C]urrent "
            f"[Enter to accept {suggestion}]: "
        ).strip().lower()
        if not response:
            return suggestion
        if response in choices:
            return choices[response]
        print("Please choose A, I, P, or C, or press Enter to accept the suggestion.")


def resolve_release_notes(
    module_dir: Path,
    module_name: str,
    version: str,
    notes: Optional[str],
) -> Optional[str]:
    """Use supplied/existing notes, or obtain a fresh proposal from Codex."""
    if notes is not None:
        return notes

    notes_path = module_dir / "RELEASE_NOTES.md"
    existing = read_top_entry(notes_path, module_name, version)
    if existing is not None:
        print(f"\nExisting release notes for {module_name} {version}:\n")
        print(existing)
        print()
        response = input(
            f"Release notes for {version} already exist. "
            "Regenerate them with Codex? [y/N] "
        )
        if response.strip().lower() != "y":
            print(f"Keeping the existing release notes for {version}.")
            return existing

    return propose_release_notes_with_codex(module_dir, version)


def print_release_summary(repo: git.Repo, notes: str) -> None:
    """Show the exact staged scope and notes immediately before confirmation."""
    print("\nGit changes ready for release:")
    status = repo.git.status("--short").strip()
    print(status or "  (no uncommitted metadata changes)")

    diff_stat = repo.git.diff("--cached", "--stat").strip()
    if diff_stat:
        print("\nStaged diff summary:")
        print(diff_stat)

    try:
        unpushed = repo.git.log("--oneline", "@{upstream}..HEAD").strip()
    except git.GitCommandError:
        unpushed = ""
    if unpushed:
        print("\nExisting commits that will also be pushed:")
        print(unpushed)

    print("\nRelease notes to commit and publish:\n")
    print(notes)



def review_staged_diff(module_dir: Path) -> bool:
    """Offer terminal review before the separate commit-and-push approval."""
    while True:
        choice = input(
            "Review in tig: [S]taged changes against HEAD, "
            "changes since [L]ast release (including staged), or [N]o review? [s/l/N] "
        ).strip().lower()
        if choice in {"", "n", "no"}:
            return True
        if choice in {"s", "staged", "y", "yes", "l", "last"}:
            break
        print("Please choose S, L, or N.")
    try:
        command = ["git", "diff", "--cached", "--no-color", "--no-ext-diff"]
        if choice in {"l", "last"}:
            tag = latest_published_tag(git.Repo(module_dir))
            if tag is None:
                print("No reachable release-version tag found; stopping before approval.")
                return False
            print(f"Reviewing all changes since release {tag.name}, including staged changes.")
            command.extend([f"refs/tags/{tag.name}", "--"])
        diff = subprocess.run(
            command, cwd=module_dir, capture_output=True, text=True,
        )
        if diff.returncode != 0:
            print(f"Could not read the requested diff: {diff.stderr.strip()}")
            return False
        if not diff.stdout:
            print("No changes to review in the selected range.")
            return True
        # Tig has no diff subcommand; feed Git's patch to its pager view.
        result = subprocess.run(
            ["tig"], input=diff.stdout, cwd=module_dir, text=True,
        )
    except (OSError, git.GitError, ValueError) as error:
        print(f"Could not review the requested diff: {error}")
        print("Changes remain staged. Install tig or review with git diff --cached.")
        return False
    if result.returncode != 0:
        print("tig failed; stopping before commit and push. Changes remain staged.")
        return False
    return True


def update_roo_testing_examples(module_dir: Path, version: str) -> Optional[List[Path]]:
    """Update roo_testing version pins in its example MODULE.bazel files.

    roo_testing is a Bazel testing framework rather than an Arduino library, so
    its release metadata consists of the module version and the examples that
    consume it.  The examples deliberately retain their other dependencies.
    """
    examples_dir = module_dir / "examples"
    if not examples_dir.is_dir():
        print("No examples directory found; no example version references to update")
        return []

    dependency_pattern = re.compile(
        r'(\bbazel_dep\s*\(\s*name\s*=\s*["\']roo_testing["\']\s*,\s*'
        r'version\s*=\s*["\'])[^"\']+(["\'])',
        re.DOTALL,
    )
    updated_files = []
    for module_bazel_path in sorted(examples_dir.rglob("MODULE.bazel")):
        try:
            content = module_bazel_path.read_text(encoding="utf-8")
            updated_content, substitutions = dependency_pattern.subn(
                rf'\g<1>{version}\g<2>', content
            )
            if substitutions:
                module_bazel_path.write_text(updated_content, encoding="utf-8")
                updated_files.append(module_bazel_path)
                print(f"  Updated {module_bazel_path.relative_to(module_dir)}")
        except OSError as error:
            print(f"Error updating {module_bazel_path}: {error}")
            return None

    if updated_files:
        print(f"✓ Updated {len(updated_files)} example version reference(s)")
    else:
        print("No roo_testing version references found in examples")
    return updated_files


def check_git_status(module_dir: Path, allow_ahead: bool = False) -> bool:
    """
    Check if git status is clean and up-to-date with upstream.
    Returns True if clean and up-to-date, False otherwise.
    """
    print(f"Checking git status in {module_dir}...")
    
    # Check for uncommitted changes using module_utils
    has_changes, changes = get_git_status(module_dir)
    if has_changes:
        print(f"Error: Git working directory is not clean in {module_dir}")
        print("Uncommitted changes:")
        for change in changes:
            print(f"  {change}")
        return False
    
    # Fetch from remote to get latest information
    print("Fetching from remote...")
    try:
        repo = git.Repo(module_dir)
        origin = repo.remotes.origin
        origin.fetch()
        print("  Fetched successfully")
    except Exception as e:
        print(f"Error: Failed to fetch from remote: {str(e)}")
        return False
    
    # Check if up-to-date with upstream using module_utils
    success, branch = get_current_branch(module_dir)
    if not success:
        if "Not on any branch" in branch:
            print("Warning: In detached HEAD state, skipping upstream checks")
            return True
        print(f"Error: {branch}")
        return False
    
    success, upstream_branch = get_upstream_branch(module_dir, branch)
    if not success:
        print("Warning: No upstream branch configured, skipping upstream checks")
        return True
    
    # Check if local is behind remote
    success, behind_count, error = count_commits_between(module_dir, branch, upstream_branch)
    if not success:
        print(f"Error: Could not check if behind remote: {error}")
        return False
    
    if behind_count > 0:
        print(f"Error: Local branch is {behind_count} commits behind {upstream_branch}")
        print("Please pull the latest changes first")
        return False
    
    # Check if local is ahead of remote
    success, ahead_count, error = count_commits_between(module_dir, upstream_branch, branch)
    if not success:
        print(f"Error: Could not check if ahead of remote: {error}")
        return False
    
    if ahead_count > 0 and not allow_ahead:
        print(f"Error: Local branch is {ahead_count} commits ahead of {upstream_branch}")
        print("Please push or reset your local changes first")
        return False
    if ahead_count > 0:
        print(
            f"  Local branch is {ahead_count} commits ahead of "
            f"{upstream_branch}; these commits will be pushed after verification"
        )
    
    print("✓ Git status is clean and up-to-date")
    return True


def read_module_bazel_version(module_bazel_path: Path) -> Optional[str]:
    """Read the version from MODULE.bazel file."""
    try:
        _, version, _ = parse_module_bazel(module_bazel_path)
    except ValueError as error:
        print(f"Error: {error}")
        return None
    if not version:
        print(f"Error: Could not find version in {module_bazel_path}")
        return None
    return version


def increment_version(version_str: str, bump_type: str) -> str:
    """
    Increment the version number according to bump_type.
    bump_type can be 'major', 'minor', 'patch', or 'current'.
    """
    version = Version(version_str)
    
    if bump_type == 'major':
        new_version = Version(f"{version.major + 1}.0.0")
    elif bump_type == 'minor':
        new_version = Version(f"{version.major}.{version.minor + 1}.0")
    elif bump_type == 'patch':
        new_version = Version(f"{version.major}.{version.minor}.{version.patch + 1}")
    elif bump_type == 'current':
        new_version = version
    else:
        raise ValueError(f"Invalid bump_type: {bump_type}")
    
    return str(new_version)


def update_module_bazel_version(module_bazel_path: Path, new_version: str) -> bool:
    """Update the version in MODULE.bazel file."""
    try:
        with open(module_bazel_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        updated_content, changed = replace_module_version(content, new_version)

        if not changed:
            print("Warning: No changes made to MODULE.bazel")
            return False
        
        with open(module_bazel_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        print(f"✓ Updated MODULE.bazel version to {new_version}")
        return True
        
    except Exception as e:
        print(f"Error updating MODULE.bazel: {e}")
        return False


def run_bazel_tests(module_dir: Path) -> bool:
    """
    Run bazel tests in the module directory.
    This runs in a subprocess and cleans up afterwards.
    """
    print(f"\nRunning bazel tests in {module_dir}...")
    
    try:
        # roo_testing's root :all suite is its release test entry point.
        # Recursive expansion also includes profile-specific support targets
        # that cannot be analyzed under the default Arduino frontend.
        if module_dir.name == ROO_TESTING_MODULE:
            bazel_cmd = ["bazel", "test", ":all"]
        else:
            bazel_cmd = ["bazel", "test", "..."]

        # Use the explicit user rc path so local Bazel cache settings are kept.
        home_bazelrc = os.path.expanduser("~/.bazelrc")
        if os.path.exists(home_bazelrc):
            bazel_cmd.insert(1, f"--bazelrc={home_bazelrc}")
        
        result = subprocess.run(
            bazel_cmd,
            cwd=module_dir,
            capture_output=False,  # Show output in real-time
            text=True,
        )
        
        if result.returncode != 0:
            print(f"✗ Bazel tests failed")
            return False
        
        print(f"✓ Bazel tests passed")
        
        # Clean up
        print("Cleaning up bazel artifacts...")
        clean_cmd = ["bazel", "clean"]
        if os.path.exists(home_bazelrc):
            clean_cmd.insert(1, f"--bazelrc={home_bazelrc}")
        subprocess.run(
            clean_cmd,
            cwd=module_dir,
            capture_output=True,
            text=True,
        )
        
        return True
        
    except Exception as e:
        print(f"Error running bazel tests: {e}")
        return False


def sync_roo_testing_files(module_dir: Path) -> bool:
    """Refresh vendored testing support from the sibling roo_testing checkout."""
    if not module_dir.name.startswith("roo_") or module_dir.name == ROO_TESTING_MODULE:
        return True
    source = module_dir.parent / ROO_TESTING_MODULE / ".roo_testing"
    print(f"\nSynchronizing testing support from {source}...")
    try:
        shutil.copytree(source, module_dir / ".roo_testing", dirs_exist_ok=True)
    except (OSError, shutil.Error) as error:
        print(f"Error synchronizing roo_testing files: {error}")
        return False
    return True


def pre_release(
    module_name: str,
    bump_type: Optional[str],
    skip_tests: bool = False,
    latest_deps: bool = True,
    notes: Optional[str] = None,
    review_diff: bool = False,
) -> bool:
    """
    Prepare a module for release.
    
    Returns True if successful, False otherwise.
    """
    # Determine paths
    script_path = Path(__file__).resolve()
    registry_dir = script_path.parent.parent  # bin -> roo-registry
    base_dir = registry_dir.parent  # roo-registry -> parent
    module_dir = base_dir / module_name
    
    print(f"Preparing {module_name} for release")
    print(f"Module directory: {module_dir}")
    
    # Validate module directory
    if not module_dir.exists() or not module_dir.is_dir():
        print(f"Error: Module directory does not exist: {module_dir}")
        return False
    
    module_bazel_path = module_dir / "MODULE.bazel"
    if not module_bazel_path.exists():
        print(f"Error: MODULE.bazel not found in {module_dir}")
        return False
    
    # Step 1: Check git status
    if not check_git_status(
        module_dir, allow_ahead=bump_type in {None, "current"}
    ):
        return False
    
    # Step 2: Read current version
    current_version = read_module_bazel_version(module_bazel_path)
    if not current_version:
        return False
    
    print(f"Current version: {current_version}")

    unchanged_tag = unchanged_since_latest_published_version(module_dir)
    if unchanged_tag is not None:
        response = input(
            f"No changes were detected since published version {unchanged_tag}. "
            "Proceed with release preparation anyway? [y/N] "
        )
        if response.strip().lower() != "y":
            print("Aborted without changing the working tree, index, or commits.")
            return False

    if not latest_deps and module_name != ROO_TESTING_MODULE:
        parsed_name, _, dependencies = parse_module_bazel(module_bazel_path)
        if parsed_name != module_name:
            print(
                f"Error: MODULE.bazel declares '{parsed_name}', "
                f"expected '{module_name}'"
            )
            return False
        print("\nValidating exact MODULE.bazel dependency versions...")
        if not validate_registry_dependencies(dependencies, registry_dir):
            return False
    
    print("\nCopying shared files from template/push...")
    try:
        shutil.copytree(
            registry_dir / "template" / "push", module_dir, dirs_exist_ok=True
        )
    except (OSError, shutil.Error) as error:
        print(f"Error copying release templates: {error}")
        return False

    if not sync_roo_testing_files(module_dir):
        return False

    # Upgrade dependencies before either Codex call so notes and version
    # recommendations include the dependency changes in the working tree.
    if latest_deps and module_name != ROO_TESTING_MODULE:
        print("\nUpgrading dependencies with update_library.py...")
        result = subprocess.run(
            build_update_library_command(
                registry_dir / "bin" / "update_library.py",
                module_name,
                latest_deps=True,
            ),
            cwd=registry_dir,
            capture_output=False,
            text=True,
        )
        if result.returncode != 0:
            print("✗ Failed to upgrade dependencies")
            return False

    # Step 3: Resolve notes and select the release version. An untagged current
    # version is already prepared but unpublished, so it must not be incremented.
    if bump_type is None and not is_version_published(module_dir, current_version):
        bump_type = "current"
        print(
            f"Version {current_version} has not been published; "
            "using the current version."
        )

    if bump_type is None:
        if notes is None:
            notes = propose_release_notes_with_codex(
                module_dir, f"after {current_version}"
            )
            if notes is None:
                return False
        bump_type = suggest_bump_type_with_codex(
            module_dir, current_version, notes
        )
        if bump_type is None:
            return False
        bump_type = confirm_bump_type(bump_type)

    try:
        new_version = increment_version(current_version, bump_type)
    except Exception as e:
        print(f"Error calculating new version: {e}")
        return False

    notes = resolve_release_notes(
        module_dir, module_name, new_version, notes
    )
    if notes is None:
        return False
    
    if bump_type == "current":
        print(f"Release version: {new_version} (unchanged)")
    else:
        print(f"New version: {new_version}")

    if module_name == ROO_TESTING_MODULE:
        dependency_policy = "not applicable (roo_testing has no Arduino metadata)"
    else:
        dependency_policy = (
            "latest versions in the local Roo registry"
            if latest_deps
            else "exact versions from MODULE.bazel"
        )
    print(f"Dependency policy: {dependency_policy}")
    
    # Step 4: Update MODULE.bazel unless the current version was requested.
    if bump_type != "current":
        if not update_module_bazel_version(module_bazel_path, new_version):
            return False

    # Step 5: Create or update the release-note draft.
    notes_path = module_dir / "RELEASE_NOTES.md"
    upsert_draft_entry(notes_path, module_name, new_version, notes)
    print(f"✓ Updated {notes_path.name} for {new_version}")

    # Step 6: Synchronize release metadata, preserving the dependency versions
    # already reviewed when generating notes and selecting the release version.
    if module_name == ROO_TESTING_MODULE:
        print("\nUpdating roo_testing example version references...")
        updated_examples = update_roo_testing_examples(module_dir, new_version)
        if updated_examples is None:
            return False
    else:
        print(f"\nRunning update_library.py...")
        update_script = registry_dir / "bin" / "update_library.py"
        update_command = build_update_library_command(
            update_script,
            module_name,
            latest_deps=False,
        )
        result = subprocess.run(
            update_command,
            cwd=registry_dir,
            capture_output=False,
            text=True,
        )

        if result.returncode != 0:
            print(f"✗ Failed to update library files")
            return False
    
    # Step 7: Run bazel tests (unless skipped)
    if not skip_tests:
        if not run_bazel_tests(module_dir):
            print("\nWarning: Tests failed. Do you want to continue anyway?")
            response = input("Continue preparing the release? [y/N] ")
            if response.lower() != 'y':
                print("Aborted. Changes remain uncommitted.")
                return False
    else:
        print("\nSkipping tests (--skip-tests flag)")
    
    # Step 8: Git add
    print(f"\nStaging changes...")
    try:
        repo = git.Repo(module_dir)
        repo.git.add("--all")
    except Exception as e:
        print(f"Error staging files: {str(e)}")
        return False

    # Step 9: Show the final staged scope and notes, then ask once before the
    # irreversible commit-and-push portion of the workflow.
    print_release_summary(repo, notes)
    if review_diff and not review_staged_diff(module_dir):
        return False
    response = input("\nContinue with commit and push? [y/N] ")
    if response.strip().lower() != "y":
        print("Aborted. Changes remain staged and uncommitted.")
        return False
    
    # Step 10: Git commit, unless --current found metadata already synchronized.
    staged_changes = list(repo.index.diff("HEAD"))
    if staged_changes:
        commit_message = (
            f"Prepare version {new_version} for release"
            if bump_type == "current"
            else f"Bump version to {new_version}"
        )
        print(f"\nCommitting changes with message: '{commit_message}'")
        try:
            repo.index.commit(commit_message)
            print("  Committed successfully")
        except Exception as e:
            print(f"Error: Failed to commit changes: {str(e)}")
            return False
        print("✓ Changes committed")
    else:
        print("\nNo release metadata changes to commit")
    
    # Step 11: Git push using module_utils
    print(f"\nPushing to remote...")
    success, message = git_push(module_dir)
    if not success:
        print(f"Error: {message}")
        return False
    print(f"✓ {message}")
    
    print(f"\n✓ Successfully prepared {module_name} version {new_version} for release")
    return True


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for pre_release.py."""
    parser = argparse.ArgumentParser(
        description="Prepare a roo module for release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script automates the release preparation process:
1. Verifies git status is clean and up-to-date
2. Copies template/push contents into the repository, overwriting matching files
3. Upgrades Roo dependencies to the latest registered versions
4. Selects or increments the version number in MODULE.bazel
5. Creates or updates the top RELEASE_NOTES.md entry
6. Updates library metadata and runs bazel tests
7. Shows and confirms the staged release, then commits and pushes it

Example: python3 roo-registry/bin/pre_release.py roo_display
        """
    )
    
    parser.add_argument(
        "module_name",
        help="Name of the module to release (e.g., roo_display)"
    )
    
    version_group = parser.add_mutually_exclusive_group()
    version_group.add_argument(
        "--major",
        action="store_const",
        const="major",
        dest="bump_type",
        help="Increment major version (x.0.0)"
    )
    version_group.add_argument(
        "--minor",
        action="store_const",
        const="minor",
        dest="bump_type",
        help="Increment minor version (0.x.0)"
    )
    version_group.add_argument(
        "--patch",
        action="store_const",
        const="patch",
        dest="bump_type",
        help="Increment patch version (0.0.x)"
    )
    version_group.add_argument(
        "--current",
        action="store_const",
        const="current",
        dest="bump_type",
        help="Prepare the version currently declared in MODULE.bazel",
    )
    
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running bazel tests"
    )
    parser.add_argument(
        "--notes",
        help=(
            "Markdown body for the release notes. When omitted, existing notes "
            "can be retained or Codex generates a proposal."
        ),
    )
    parser.add_argument(
        "--nolatest_deps",
        "--no-latest-deps",
        action="store_true",
        help=(
            "Preserve exact MODULE.bazel dependency versions, verify their "
            "Roo registry entries, and only synchronize library metadata"
        ),
    )
    return parser


def main():
    """Main function."""
    args = create_argument_parser().parse_args()

    success = pre_release(
        args.module_name,
        args.bump_type,
        args.skip_tests,
        latest_deps=not args.nolatest_deps,
        notes=args.notes,
    )
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
