#!/usr/bin/env python3
"""
Script to synchronize the local state of all roo modules with GitHub.

This script:
1. Handles roo-registry repository: pushes local changes and pulls remote changes
2. Scans roo-registry/modules directory to find tracked modules
3. For each module: pushes local changes and pulls remote changes
4. Provides a summary of uncommitted changes and sync failures

Usage: python3 roo-registry/bin/sync.py
"""

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Tuple, Dict, Optional


def run_git_command(repo_path: Path, command: List[str]) -> Tuple[bool, str, str]:
    """
    Run a git command in the specified repository.
    Returns (success, stdout, stderr).
    """
    try:
        result = subprocess.run(
            ["git"] + command,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def has_uncommitted_changes(repo_path: Path) -> Tuple[bool, List[str]]:
    """Check if repository has uncommitted changes. Returns (has_changes, list_of_changes)."""
    success, stdout, stderr = run_git_command(repo_path, ["status", "--porcelain"])
    if not success:
        return False, []
    
    changes = [line.strip() for line in stdout.split('\n') if line.strip()]
    return len(changes) > 0, changes


def has_unpushed_commits(repo_path: Path) -> Tuple[bool, str]:
    """Check if repository has unpushed commits. Returns (has_unpushed, branch_info)."""
    # Get current branch
    success, branch, stderr = run_git_command(repo_path, ["branch", "--show-current"])
    if not success:
        return False, f"Could not determine current branch: {stderr}"
    
    if not branch:
        return False, "Not on any branch (detached HEAD)"
    
    # Check if branch has upstream
    success, upstream, stderr = run_git_command(
        repo_path, ["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"]
    )
    if not success:
        return False, f"No upstream branch configured for {branch}"
    
    # Check for unpushed commits
    success, commits, stderr = run_git_command(
        repo_path, ["rev-list", f"{upstream}..{branch}", "--count"]
    )
    if not success:
        return False, f"Could not check unpushed commits: {stderr}"
    
    try:
        count = int(commits)
        return count > 0, f"{count} unpushed commits on {branch}"
    except ValueError:
        return False, f"Invalid commit count: {commits}"


def git_push(repo_path: Path) -> Tuple[bool, str]:
    """Push commits to remote. Returns (success, message)."""
    success, stdout, stderr = run_git_command(repo_path, ["push"])
    if success:
        return True, "Successfully pushed"
    else:
        return False, f"Push failed: {stderr or stdout}"


def has_remote_changes(repo_path: Path) -> Tuple[bool, str]:
    """Check if there are remote changes to pull. Returns (has_remote_changes, info)."""
    # First, fetch to get latest remote info
    success, _, stderr = run_git_command(repo_path, ["fetch"])
    if not success:
        return False, f"Could not fetch from remote: {stderr}"
    
    # Get current branch
    success, branch, stderr = run_git_command(repo_path, ["branch", "--show-current"])
    if not success:
        return False, f"Could not determine current branch: {stderr}"
    
    if not branch:
        return False, "Not on any branch (detached HEAD)"
    
    # Check if branch has upstream
    success, upstream, stderr = run_git_command(
        repo_path, ["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"]
    )
    if not success:
        return False, f"No upstream branch configured for {branch}"
    
    # Check for commits ahead on remote
    success, commits, stderr = run_git_command(
        repo_path, ["rev-list", f"{branch}..{upstream}", "--count"]
    )
    if not success:
        return False, f"Could not check remote changes: {stderr}"
    
    try:
        count = int(commits)
        return count > 0, f"{count} remote changes available" if count > 0 else "No remote changes"
    except ValueError:
        return False, f"Invalid remote change count: {commits}"


def git_pull_rebase(repo_path: Path) -> Tuple[bool, str]:
    """Pull with rebase from remote. Returns (success, message)."""
    success, stdout, stderr = run_git_command(repo_path, ["pull", "--rebase"])
    if success:
        return True, "Successfully pulled with rebase"
    else:
        return False, f"Pull rebase failed: {stderr or stdout}"


def git_clone(repo_url: str, target_path: Path) -> Tuple[bool, str]:
    """Clone a repository from GitHub. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(target_path)],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode == 0:
            return True, "Successfully cloned"
        else:
            return False, f"Clone failed: {result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return False, "Clone timed out"
    except Exception as e:
        return False, f"Clone failed: {str(e)}"


def sync_repository(repo_path: Path, repo_name: str, clone_url: str = None) -> Tuple[bool, List[str]]:
    """
    Sync a single repository.
    Returns (overall_success, list_of_error_messages).
    """
    error_messages = []
    
    # Check if repository exists, clone if missing
    if not repo_path.exists():
        if clone_url:
            print(f"Syncing {repo_name} ... cloning", end="", flush=True)
            clone_success, clone_msg = git_clone(clone_url, repo_path)
            if not clone_success:
                print(" ✗")
                return False, [f"{repo_name}: {clone_msg}"]
            print(" cloned", end="", flush=True)
        else:
            print(f"Syncing {repo_name} ... ✗")
            return False, [f"{repo_name}: Directory does not exist and no clone URL provided"]
    else:
        print(f"Syncing {repo_name} ...", end="", flush=True)
    
    # Check if it's a git repository
    if not (repo_path / ".git").exists():
        print(" ✗")
        return False, [f"{repo_name}: Not a git repository"]
    
    status_printed = False
    
    # Step 1: Pull with rebase first
    pull_success, pull_msg = git_pull_rebase(repo_path)
    if not pull_success:
        # Check if the failure is due to uncommitted changes and no remote changes
        if "unstaged changes" in pull_msg.lower() or "uncommitted changes" in pull_msg.lower():
            has_remote, remote_info = has_remote_changes(repo_path)
            if not has_remote and "No remote changes" in remote_info:
                # No remote changes and pull failed due to local changes - this is OK
                print(" OK")
                status_printed = True
                pull_success = True  # Treat as success for push check
            else:
                # There are remote changes but can't pull due to local changes - this is a failure
                print(" ✗")
                status_printed = True
                error_messages.append(f"{repo_name}: {pull_msg}")
        else:
            # Other pull failure
            print(" ✗")
            status_printed = True
            error_messages.append(f"{repo_name}: {pull_msg}")
    
    # Step 2: Check for unpushed commits and push if needed (only if pull succeeded)
    if pull_success:
        has_unpushed, push_info = has_unpushed_commits(repo_path)
        if has_unpushed:
            push_success, push_msg = git_push(repo_path)
            if not push_success:
                if not status_printed:
                    print(" ✗")
                error_messages.append(f"{repo_name}: {push_msg}")
            else:
                if not status_printed:
                    print(" OK")
        else:
            # Check if push info indicates an issue
            if "No upstream branch" in push_info or "Could not" in push_info:
                if not status_printed:
                    print(" ⚠️")
                error_messages.append(f"{repo_name}: {push_info}")
            else:
                if not status_printed:
                    print(" OK")
    
    return len(error_messages) == 0, error_messages


def find_module_directories(modules_dir: Path) -> List[Tuple[str, Path]]:
    """
    Find all module directories in the modules directory.
    Returns list of (module_name, module_path) tuples.
    """
    modules = []
    if not modules_dir.exists():
        return modules
    
    for item in modules_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            modules.append((item.name, item))
    
    return sorted(modules)


def get_roo_module_paths(roo_dir: Path, modules: List[Tuple[str, Path]]) -> List[Tuple[str, Path, str]]:
    """
    Get paths to actual roo module repositories (siblings to roo-registry).
    Returns list of (module_name, repo_path, clone_url) tuples.
    """
    module_repos = []
    
    for module_name, _ in modules:
        # Look for module directory as sibling to roo-registry
        module_path = roo_dir / module_name
        clone_url = f"https://github.com/dejwk/{module_name}.git"
        module_repos.append((module_name, module_path, clone_url))
    
    return module_repos


def main():
    """Main function."""
    print("Roo Module Sync")
    print("===============")
    
    # Get paths
    script_dir = Path(__file__).parent.absolute()
    registry_dir = script_dir.parent  # roo-registry directory
    roo_dir = registry_dir.parent     # roo directory (parent of roo-registry)
    modules_dir = registry_dir / "modules"
    
    print(f"Registry directory: {registry_dir}")
    print(f"Roo directory: {roo_dir}")
    print()
    
    # Track results
    failed_repos = {}  # repo_name -> list of error messages
    
    # Step 1: Sync roo-registry repository
    print("=" * 60)
    registry_success, registry_errors = sync_repository(registry_dir, "roo-registry")
    if not registry_success:
        failed_repos["roo-registry"] = registry_errors
    
    # Step 2: Find tracked modules
    print("\n" + "=" * 60)
    print("Finding tracked modules...")
    tracked_modules = find_module_directories(modules_dir)
    print(f"Found {len(tracked_modules)} tracked modules")
    
    # Step 3: Find corresponding module repositories
    module_repos = get_roo_module_paths(roo_dir, tracked_modules)
    print(f"Processing {len(module_repos)} modules")
    
    # Step 4: Sync each module repository
    print("\n" + "=" * 60)
    for module_name, module_path, clone_url in module_repos:
        module_success, module_errors = sync_repository(module_path, module_name, clone_url)
        if not module_success:
            failed_repos[module_name] = module_errors
    
    # Step 5: Generate summary
    print("=" * 60)
    print("SYNC SUMMARY")
    print("=" * 60)
    
    # Check for uncommitted changes
    print("\nModules with uncommitted changes:")
    modules_with_uncommitted = []
    
    # Check roo-registry
    has_changes, changes = has_uncommitted_changes(registry_dir)
    if has_changes:
        modules_with_uncommitted.append(("roo-registry", changes))
    
    # Check each module
    for module_name, module_path, _ in module_repos:
        if module_path.exists():  # Only check if directory exists
            has_changes, changes = has_uncommitted_changes(module_path)
            if has_changes:
                modules_with_uncommitted.append((module_name, changes))
    
    if modules_with_uncommitted:
        for repo_name, changes in modules_with_uncommitted:
            print(f"  {repo_name}:")
            for change in changes[:5]:  # Limit to first 5 changes
                print(f"    {change}")
            if len(changes) > 5:
                print(f"    ... and {len(changes) - 5} more changes")
    else:
        print("  ✓ No modules have uncommitted changes")
    
    # Report sync failures
    print("\nSync failures:")
    if failed_repos:
        for repo_name, error_messages in failed_repos.items():
            print(f"  {repo_name}:")
            for msg in error_messages:
                print(f"    ✗ {msg}")
    else:
        print("  ✓ All syncs completed successfully")
    
    # Overall status
    total_repos = 1 + len(module_repos)  # roo-registry + modules
    failed_count = len(failed_repos)
    success_count = total_repos - failed_count
    
    print(f"\nOverall: {success_count}/{total_repos} repositories synced successfully")
    
    if failed_repos:
        print("\n⚠️  Some repositories failed to sync. Please check the errors above.")
        return 1
    else:
        print("\n✓ All repositories synced successfully!")
        return 0


if __name__ == "__main__":
    sys.exit(main())