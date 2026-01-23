#!/usr/bin/env python3
"""
Script to prepare a module for release by incrementing version and updating files.

Usage: python3 roo-registry/bin/pre_release.py <module_name> --major|--minor|--patch

This script will:
1. Verify git status is clean and up-to-date with upstream
2. Increment the version number in MODULE.bazel
3. Update library.json and library.properties
4. Commit and push the changes
5. Run bazel tests in a subprocess

Example: python3 roo-registry/bin/pre_release.py roo_display --patch
"""

import sys
import os
import subprocess
import argparse
import re
from pathlib import Path
from typing import Tuple, Optional

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import (
    Version, parse_module_bazel, get_git_status, run_git_command, 
    has_remote_changes, count_commits_between, get_current_branch, 
    get_upstream_branch, git_push
)


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


def check_git_status(module_dir: Path) -> bool:
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
    success, _, stderr = run_git_command(module_dir, ["fetch"])
    if not success:
        print(f"Error: Failed to fetch from remote: {stderr}")
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
    
    if ahead_count > 0:
        print(f"Error: Local branch is {ahead_count} commits ahead of {upstream_branch}")
        print("Please push or reset your local changes first")
        return False
    
    print("✓ Git status is clean and up-to-date")
    return True


def read_module_bazel_version(module_bazel_path: Path) -> Optional[str]:
    """Read the version from MODULE.bazel file."""
    try:
        with open(module_bazel_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Match: module(name = "...", version = "x.y.z")
        pattern = r'module\s*\(\s*name\s*=\s*"[^"]+"\s*,\s*version\s*=\s*"([^"]+)"\s*\)'
        match = re.search(pattern, content)
        
        if match:
            return match.group(1)
        else:
            print(f"Error: Could not find version in {module_bazel_path}")
            return None
            
    except Exception as e:
        print(f"Error reading MODULE.bazel: {e}")
        return None


def increment_version(version_str: str, bump_type: str) -> str:
    """
    Increment the version number according to bump_type.
    bump_type can be 'major', 'minor', or 'patch'.
    """
    version = Version(version_str)
    
    if bump_type == 'major':
        new_version = Version(f"{version.major + 1}.0.0")
    elif bump_type == 'minor':
        new_version = Version(f"{version.major}.{version.minor + 1}.0")
    elif bump_type == 'patch':
        new_version = Version(f"{version.major}.{version.minor}.{version.patch + 1}")
    else:
        raise ValueError(f"Invalid bump_type: {bump_type}")
    
    return str(new_version)


def update_module_bazel_version(module_bazel_path: Path, new_version: str) -> bool:
    """Update the version in MODULE.bazel file."""
    try:
        with open(module_bazel_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace version in module() declaration
        pattern = r'(module\s*\(\s*name\s*=\s*"[^"]+"\s*,\s*version\s*=\s*")[^"]+(")'
        updated_content = re.sub(pattern, rf'\g<1>{new_version}\g<2>', content)
        
        if updated_content == content:
            print(f"Warning: No changes made to MODULE.bazel")
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
        # Run bazel test with explicit bazelrc to use user's cache settings
        home_bazelrc = os.path.expanduser("~/.bazelrc")
        bazel_cmd = ["bazel", "test", "..."]
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


def pre_release(module_name: str, bump_type: str, skip_tests: bool = False) -> bool:
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
    if not check_git_status(module_dir):
        return False
    
    # Step 2: Read current version
    current_version = read_module_bazel_version(module_bazel_path)
    if not current_version:
        return False
    
    print(f"Current version: {current_version}")
    
    # Step 3: Calculate new version
    try:
        new_version = increment_version(current_version, bump_type)
    except Exception as e:
        print(f"Error calculating new version: {e}")
        return False
    
    print(f"New version: {new_version}")
    
    # Confirm with user
    response = input(f"\nProceed with version bump {current_version} -> {new_version}? [y/N] ")
    if response.lower() != 'y':
        print("Aborted by user")
        return False
    
    # Step 4: Update MODULE.bazel
    if not update_module_bazel_version(module_bazel_path, new_version):
        return False
    
    # Step 5: Run update_library.py
    print(f"\nRunning update_library.py...")
    update_script = registry_dir / "bin" / "update_library.py"
    result = subprocess.run(
        [sys.executable, str(update_script), module_name],
        cwd=registry_dir,
        capture_output=False,
        text=True,
    )
    
    if result.returncode != 0:
        print(f"✗ Failed to update library files")
        return False
    
    # Step 6: Run bazel tests (unless skipped)
    if not skip_tests:
        if not run_bazel_tests(module_dir):
            print("\nWarning: Tests failed. Do you want to continue anyway?")
            response = input("Continue with commit and push? [y/N] ")
            if response.lower() != 'y':
                print("Aborted. Changes are staged but not committed.")
                return False
    else:
        print("\nSkipping tests (--skip-tests flag)")
    
    # Step 7: Git add
    print(f"\nStaging changes...")
    files_to_add = ["MODULE.bazel", "library.json", "library.properties"]
    for file in files_to_add:
        file_path = module_dir / file
        if file_path.exists():
            success, _, stderr = run_git_command(module_dir, ["add", file])
            if success:
                print(f"  Staged: {file}")
            else:
                print(f"  Warning: Failed to stage {file}: {stderr}")
    
    # Step 8: Git commit
    commit_message = f"Bump version to {new_version}"
    print(f"\nCommitting changes with message: '{commit_message}'")
    success, _, stderr = run_git_command(module_dir, ["commit", "-m", commit_message])
    if not success:
        print(f"Error: Failed to commit changes: {stderr}")
        return False
    print("✓ Changes committed")
    
    # Step 9: Git push using module_utils
    print(f"\nPushing to remote...")
    success, message = git_push(module_dir)
    if not success:
        print(f"Error: {message}")
        return False
    print(f"✓ {message}")
    
    print(f"\n✓ Successfully prepared {module_name} version {new_version} for release")
    return True


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Prepare a roo module for release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script automates the release preparation process:
1. Verifies git status is clean and up-to-date
2. Increments the version number in MODULE.bazel
3. Updates library.json and library.properties
4. Runs bazel tests
5. Commits and pushes the changes

Example: python3 roo-registry/bin/pre_release.py roo_display --patch
        """
    )
    
    parser.add_argument(
        "module_name",
        help="Name of the module to release (e.g., roo_display)"
    )
    
    version_group = parser.add_mutually_exclusive_group(required=True)
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
    
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip running bazel tests"
    )
    
    args = parser.parse_args()
    
    success = pre_release(args.module_name, args.bump_type, args.skip_tests)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
