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
import subprocess
import argparse
import re
from pathlib import Path
from typing import Tuple, Optional

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import Version


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
    
    # Check for uncommitted changes
    result = run_command(["git", "status", "--porcelain"], cwd=module_dir, check=False)
    if result.stdout.strip():
        print(f"Error: Git working directory is not clean in {module_dir}")
        print("Uncommitted changes:")
        print(result.stdout)
        return False
    
    # Fetch from remote to get latest information
    print("Fetching from remote...")
    run_command(["git", "fetch"], cwd=module_dir)
    
    # Check if up-to-date with upstream
    result = run_command(
        ["git", "rev-parse", "--abbrev-ref", "@{u}"],
        cwd=module_dir,
        check=False
    )
    
    if result.returncode != 0:
        print("Warning: No upstream branch configured")
        # Allow continuing if no upstream is set
        return True
    
    upstream_branch = result.stdout.strip()
    
    # Check if local is behind remote
    result = run_command(
        ["git", "rev-list", "--count", f"HEAD..{upstream_branch}"],
        cwd=module_dir,
        check=False
    )
    
    if result.returncode == 0 and result.stdout.strip() != "0":
        print(f"Error: Local branch is behind {upstream_branch}")
        print(f"Please pull the latest changes first")
        return False
    
    # Check if local is ahead of remote
    result = run_command(
        ["git", "rev-list", "--count", f"{upstream_branch}..HEAD"],
        cwd=module_dir,
        check=False
    )
    
    if result.returncode == 0 and result.stdout.strip() != "0":
        print(f"Error: Local branch is ahead of {upstream_branch}")
        print(f"Please push or reset your local changes first")
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
        # Run bazel test
        result = subprocess.run(
            ["bazel", "test", "..."],
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
        subprocess.run(
            ["bazel", "clean"],
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
            run_command(["git", "add", file], cwd=module_dir)
            print(f"  Staged: {file}")
    
    # Step 8: Git commit
    commit_message = f"Bump version to {new_version}"
    print(f"\nCommitting changes with message: '{commit_message}'")
    run_command(["git", "commit", "-m", commit_message], cwd=module_dir)
    print("✓ Changes committed")
    
    # Step 9: Git push
    print(f"\nPushing to remote...")
    run_command(["git", "push"], cwd=module_dir)
    print("✓ Changes pushed to remote")
    
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
