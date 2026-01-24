#!/usr/bin/env python3
"""
Script to finalize a module release by updating the registry and publishing.

Usage: python3 roo-registry/bin/post_release.py <module_name>

This script will:
1. Clean and pull the module directory
2. Add the new version to the registry
3. Update the dependency graph
4. Amend the commit to include dependency graph changes
5. Push to remote
6. Publish to PlatformIO registry

Example: python3 roo-registry/bin/post_release.py roo_display
"""

import sys
import subprocess
import argparse
import re
from pathlib import Path
from typing import Optional

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import parse_module_bazel, git_push


def run_command(cmd: list, cwd: Optional[Path] = None, check: bool = True, show_output: bool = False) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=not show_output,
        text=True,
    )
    if check and result.returncode != 0:
        print(f"Error running command: {' '.join(cmd)}")
        if not show_output:
            print(f"stdout: {result.stdout}")
            print(f"stderr: {result.stderr}")
        sys.exit(1)
    return result


def clean_and_pull_module(module_dir: Path) -> bool:
    """
    Clean bazel artifacts and pull latest changes in module directory.
    """
    print(f"\nCleaning and updating {module_dir.name}...")
    
    # Run bazel clean
    print("  Running bazel clean...")
    result = run_command(
        ["bazel", "clean"],
        cwd=module_dir,
        check=False
    )
    
    if result.returncode != 0:
        print(f"  Warning: bazel clean failed (module may not use bazel)")
    else:
        print("  ✓ Bazel clean completed")
    
    # Run git pull
    print("  Running git pull...")
    try:
        repo = git.Repo(module_dir)
        origin = repo.remotes.origin
        current_branch = repo.active_branch.name
        repo.git.pull('origin', current_branch)
        print("    Git pull successful")
    except Exception as e:
        print(f"  Warning: Git pull failed: {str(e)}")
        return False
    print("  ✓ Git pull completed")
    
    return True


def get_module_version(module_dir: Path) -> Optional[str]:
    """Get the version from MODULE.bazel in the module directory."""
    module_bazel_path = module_dir / "MODULE.bazel"
    
    if not module_bazel_path.exists():
        print(f"Error: MODULE.bazel not found in {module_dir}")
        return None
    
    try:
        _, version, _ = parse_module_bazel(module_bazel_path)
        return version
    except Exception as e:
        print(f"Error parsing MODULE.bazel: {e}")
        return None


def add_to_registry(registry_dir: Path, module_name: str, version: str) -> bool:
    """
    Call bin/add.sh to add the module version to the registry.
    """
    print(f"\nAdding {module_name} version {version} to registry...")
    
    add_script = registry_dir / "bin" / "add.sh"
    
    if not add_script.exists():
        print(f"Error: add.sh not found at {add_script}")
        return False
    
    result = run_command(
        ["bash", str(add_script), module_name, version],
        cwd=registry_dir,
        check=False,
        show_output=True
    )
    
    if result.returncode != 0:
        print(f"✗ Failed to add module to registry")
        return False
    
    print(f"✓ Added {module_name} {version} to registry")
    return True


def generate_dependency_graph(registry_dir: Path) -> bool:
    """
    Call bin/generate_dependency_graph.py to update the dependency graph.
    """
    print(f"\nGenerating dependency graph...")
    
    graph_script = registry_dir / "bin" / "generate_dependency_graph.py"
    
    if not graph_script.exists():
        print(f"Error: generate_dependency_graph.py not found at {graph_script}")
        return False
    
    result = run_command(
        [sys.executable, str(graph_script)],
        cwd=registry_dir.parent,  # Run from parent directory as expected by the script
        check=False,
        show_output=True
    )
    
    if result.returncode != 0:
        print(f"✗ Failed to generate dependency graph")
        return False
    
    print(f"✓ Dependency graph generated")
    return True


def amend_commit_with_graph(registry_dir: Path) -> bool:
    """
    Amend the last commit to include the updated dependency graph files.
    """
    print(f"\nAmending commit to include dependency graph...")
    
    # Stage dependency graph files
    doc_dir = registry_dir / "doc"
    graph_files = ["dependencies.dot", "dependencies.svg"]
    
    staged_files = []
    for file in graph_files:
        file_path = doc_dir / file
        if file_path.exists():
            success, _, stderr = run_git_command(registry_dir, ["add", str(file_path)])
            if success:
                staged_files.append(file)
                print(f"  Staged: {file}")
            else:
                print(f"  Warning: Failed to stage {file}: {stderr}")
        else:
            print(f"  Warning: {file} not found")
    
    if not staged_files:
        print(f"  Warning: No dependency graph files found to add")
        return True
    
    # Amend the last commit
    try:
        repo = git.Repo(registry_dir)
        repo.git.commit('--amend', '--no-edit')
        print("  Amended commit with dependency graph updates")
    except Exception as e:
        print(f"  Error: Failed to amend commit: {str(e)}")
        return False
    
    print(f"✓ Amended commit with dependency graph files")
    return True


def push_registry_changes(registry_dir: Path) -> bool:
    """
    Push the registry changes to remote.
    """
    print(f"\nPushing registry changes...")
    
    # Need to force push since we amended the commit
    try:
        repo = git.Repo(registry_dir)
        origin = repo.remotes.origin
        current_branch = repo.active_branch.name
        repo.git.push('--force-with-lease', 'origin', current_branch)
        print("  Registry changes pushed successfully")
    except Exception as e:
        print(f"  Error: Failed to push: {str(e)}")
        return False
    
    print(f"✓ Registry changes pushed to remote")
    return True


def find_pio_executable() -> Optional[str]:
    """
    Find the PlatformIO executable.
    Tries multiple methods to locate it.
    """
    # Method 1: Check if pio is in PATH
    result = subprocess.run(
        ["which", "pio"],
        capture_output=True,
        text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    
    # Method 2: Check common installation location
    home = Path.home()
    common_path = home / ".platformio" / "penv" / "bin" / "pio"
    if common_path.exists():
        return str(common_path)
    
    # Method 3: Try to find using command -v
    result = subprocess.run(
        ["command", "-v", "pio"],
        shell=True,
        capture_output=True,
        text=True
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    
    return None


def publish_to_platformio(module_dir: Path) -> bool:
    """
    Publish the module to PlatformIO registry.
    """
    print(f"\nPublishing {module_dir.name} to PlatformIO...")
    
    # Find the pio executable
    pio_path = find_pio_executable()
    
    if not pio_path:
        print(f"Error: Could not find 'pio' executable")
        print(f"Please ensure PlatformIO is installed")
        print(f"Tried:")
        print(f"  - PATH lookup")
        print(f"  - ~/.platformio/penv/bin/pio")
        return False
    
    print(f"Using pio at: {pio_path}")
    
    result = run_command(
        [pio_path, "pkg", "publish"],
        cwd=module_dir,
        check=False,
        show_output=True
    )
    
    if result.returncode != 0:
        print(f"✗ Failed to publish to PlatformIO")
        return False
    
    print(f"✓ Published to PlatformIO")
    return True


def post_release(module_name: str, skip_publish: bool = False) -> bool:
    """
    Finalize the release of a module.
    
    Returns True if successful, False otherwise.
    """
    # Determine paths
    script_path = Path(__file__).resolve()
    registry_dir = script_path.parent.parent  # bin -> roo-registry
    base_dir = registry_dir.parent  # roo-registry -> parent
    module_dir = base_dir / module_name
    
    print(f"Finalizing release for {module_name}")
    print(f"Module directory: {module_dir}")
    print(f"Registry directory: {registry_dir}")
    
    # Validate module directory
    if not module_dir.exists() or not module_dir.is_dir():
        print(f"Error: Module directory does not exist: {module_dir}")
        return False
    
    # Step 1: Clean and pull module
    if not clean_and_pull_module(module_dir):
        return False
    
    # Step 2: Get the module version
    version = get_module_version(module_dir)
    if not version:
        print(f"Error: Could not determine module version")
        return False
    
    print(f"\nModule version: {version}")
    
    # Step 3: Add to registry
    if not add_to_registry(registry_dir, module_name, version):
        return False
    
    # Step 4: Generate dependency graph
    if not generate_dependency_graph(registry_dir):
        return False
    
    # Step 5: Amend commit to include dependency graph
    if not amend_commit_with_graph(registry_dir):
        return False
    
    # Step 6: Push registry changes
    if not push_registry_changes(registry_dir):
        return False
    
    # Step 7: Publish to PlatformIO (unless skipped)
    if not skip_publish:
        if not publish_to_platformio(module_dir):
            print("\nWarning: PlatformIO publish failed.")
            response = input("Continue anyway? [y/N] ")
            if response.lower() != 'y':
                print("Aborted.")
                return False
    else:
        print("\nSkipping PlatformIO publish (--skip-publish flag)")
    
    print(f"\n✓ Successfully finalized release for {module_name} version {version}")
    return True


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Finalize a roo module release",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script automates the post-release process:
1. Cleans bazel artifacts and pulls latest changes
2. Adds the new version to the registry
3. Updates the dependency graph
4. Amends the commit to include dependency graph changes
5. Pushes to remote
6. Publishes to PlatformIO registry

Example: python3 roo-registry/bin/post_release.py roo_display
        """
    )
    
    parser.add_argument(
        "module_name",
        help="Name of the module to release (e.g., roo_display)"
    )
    
    parser.add_argument(
        "--skip-publish",
        action="store_true",
        help="Skip publishing to PlatformIO"
    )
    
    args = parser.parse_args()
    
    success = post_release(args.module_name, args.skip_publish)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
