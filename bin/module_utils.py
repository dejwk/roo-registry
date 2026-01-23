#!/usr/bin/env python3
"""
Shared utilities for working with roo modules and their dependencies.
"""

import os
import re
import subprocess
from typing import List, Tuple, Dict, Set, Optional
from pathlib import Path


def run_git_command(repo_path: Path, command: List[str], timeout: int = 30) -> Tuple[bool, str, str]:
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
            timeout=timeout
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def get_git_status(repo_path: Path) -> Tuple[bool, List[str]]:
    """
    Check if repository has uncommitted changes.
    Returns (has_changes, list_of_changes).
    """
    success, stdout, stderr = run_git_command(repo_path, ["status", "--porcelain"])
    if not success:
        return False, []
    
    changes = [line.strip() for line in stdout.split('\n') if line.strip()]
    return len(changes) > 0, changes


def get_current_branch(repo_path: Path) -> Tuple[bool, str]:
    """
    Get the current branch name.
    Returns (success, branch_name_or_error_msg).
    """
    success, branch, stderr = run_git_command(repo_path, ["branch", "--show-current"])
    if not success:
        return False, f"Could not determine current branch: {stderr}"
    
    if not branch:
        return False, "Not on any branch (detached HEAD)"
    
    return True, branch


def get_upstream_branch(repo_path: Path, branch: str) -> Tuple[bool, str]:
    """
    Get the upstream branch for the given branch.
    Returns (success, upstream_branch_or_error_msg).
    """
    success, upstream, stderr = run_git_command(
        repo_path, ["rev-parse", "--abbrev-ref", f"{branch}@{{upstream}}"]
    )
    if not success:
        return False, f"No upstream branch configured for {branch}"
    
    return True, upstream


def count_commits_between(repo_path: Path, base: str, head: str) -> Tuple[bool, int, str]:
    """
    Count commits between two references.
    Returns (success, commit_count, error_msg_if_failed).
    """
    success, commits, stderr = run_git_command(
        repo_path, ["rev-list", f"{base}..{head}", "--count"]
    )
    if not success:
        return False, 0, stderr
    
    try:
        count = int(commits)
        return True, count, ""
    except ValueError:
        return False, 0, f"Invalid commit count: {commits}"


def has_unpushed_commits(repo_path: Path) -> Tuple[bool, str]:
    """
    Check if repository has unpushed commits.
    Returns (has_unpushed, info_message).
    """
    # Get current branch
    success, branch = get_current_branch(repo_path)
    if not success:
        return False, branch  # branch contains error message
    
    # Get upstream branch
    success, upstream = get_upstream_branch(repo_path, branch)
    if not success:
        return False, upstream  # upstream contains error message
    
    # Count unpushed commits
    success, count, error = count_commits_between(repo_path, upstream, branch)
    if not success:
        return False, f"Could not check unpushed commits: {error}"
    
    return count > 0, f"{count} unpushed commits on {branch}"


def has_remote_changes(repo_path: Path) -> Tuple[bool, str]:
    """
    Check if there are remote changes to pull.
    Returns (has_remote_changes, info_message).
    """
    # First, fetch to get latest remote info
    success, _, stderr = run_git_command(repo_path, ["fetch"])
    if not success:
        return False, f"Could not fetch from remote: {stderr}"
    
    # Get current branch
    success, branch = get_current_branch(repo_path)
    if not success:
        return False, branch  # branch contains error message
    
    # Get upstream branch  
    success, upstream = get_upstream_branch(repo_path, branch)
    if not success:
        return False, upstream  # upstream contains error message
    
    # Count remote changes
    success, count, error = count_commits_between(repo_path, branch, upstream)
    if not success:
        return False, f"Could not check remote changes: {error}"
    
    return count > 0, f"{count} remote changes available" if count > 0 else "No remote changes"


def git_push(repo_path: Path) -> Tuple[bool, str]:
    """Push commits to remote. Returns (success, message)."""
    success, stdout, stderr = run_git_command(repo_path, ["push"])
    if success:
        return True, "Successfully pushed"
    else:
        return False, f"Push failed: {stderr or stdout}"


def git_pull_rebase(repo_path: Path) -> Tuple[bool, str]:
    """Pull with rebase from remote. Returns (success, message)."""
    success, stdout, stderr = run_git_command(repo_path, ["pull", "--rebase"])
    if success:
        return True, "Successfully pulled with rebase"
    else:
        return False, f"Pull rebase failed: {stderr or stdout}"


def git_clone(repo_url: str, target_path: Path, timeout: int = 60) -> Tuple[bool, str]:
    """Clone a repository from GitHub. Returns (success, message)."""
    try:
        result = subprocess.run(
            ["git", "clone", repo_url, str(target_path)],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        if result.returncode == 0:
            return True, "Successfully cloned"
        else:
            return False, f"Clone failed: {result.stderr or result.stdout}"
    except subprocess.TimeoutExpired:
        return False, "Clone timed out"
    except Exception as e:
        return False, f"Clone failed: {str(e)}"


class Version:
    """Class to represent and compare semantic versions."""
    
    def __init__(self, version_str: str):
        self.original = version_str
        # Parse semantic version (major.minor.patch)
        match = re.match(r'^(\d+)\.(\d+)\.(\d+)(?:-(.+))?$', version_str)
        if not match:
            raise ValueError(f"Invalid version format: {version_str}")
        
        self.major = int(match.group(1))
        self.minor = int(match.group(2))
        self.patch = int(match.group(3))
        self.prerelease = match.group(4) if match.group(4) else None
    
    def __lt__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        
        # Compare major, minor, patch
        self_tuple = (self.major, self.minor, self.patch)
        other_tuple = (other.major, other.minor, other.patch)
        
        if self_tuple != other_tuple:
            return self_tuple < other_tuple
        
        # If versions are equal, prerelease versions are less than normal versions
        if self.prerelease is None and other.prerelease is not None:
            return False
        if self.prerelease is not None and other.prerelease is None:
            return True
        if self.prerelease is not None and other.prerelease is not None:
            return self.prerelease < other.prerelease
        
        return False
    
    def __eq__(self, other):
        if not isinstance(other, Version):
            return NotImplemented
        return (self.major, self.minor, self.patch, self.prerelease) == \
               (other.major, other.minor, other.patch, other.prerelease)
    
    def __str__(self):
        return self.original
    
    def __repr__(self):
        return f"Version('{self.original}')"


class Dependency:
    """Class to represent a module dependency."""
    
    def __init__(self, name: str, version: str):
        self.name = name
        self.version = Version(version)
    
    def __str__(self):
        return f"{self.name}@{self.version}"
    
    def __repr__(self):
        return f"Dependency('{self.name}', '{self.version}')"


def parse_module_bazel(module_bazel_path: Path) -> Tuple[str, str, List[Dependency]]:
    """
    Parse a MODULE.bazel file and extract module info and dependencies.
    
    Returns:
        Tuple of (module_name, module_version, dependencies_list)
    """
    dependencies = []
    module_name = None
    module_version = None
    
    # Dependencies to ignore (external/third-party dependencies)
    ignored_deps = {"googletest", "rules_proto", "glog"}
    
    if not module_bazel_path.exists():
        return module_name, module_version, dependencies
    
    try:
        with open(module_bazel_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Extract module declaration
        # Pattern: module(name = "module_name", version = "x.y.z")
        module_pattern = r'module\s*\(\s*name\s*=\s*["\']([^"\']+)["\']\s*,\s*version\s*=\s*["\']([^"\']+)["\']\s*\)'
        module_match = re.search(module_pattern, content)
        if module_match:
            module_name = module_match.group(1)
            module_version = module_match.group(2)
        
        # Find all bazel_dep declarations
        # Pattern: bazel_dep(name = "dependency_name", version = "x.y.z")
        dep_pattern = r'bazel_dep\s*\(\s*name\s*=\s*["\']([^"\']+)["\']\s*,\s*version\s*=\s*["\']([^"\']+)["\']\s*\)'
        
        for match in re.finditer(dep_pattern, content):
            dep_name = match.group(1)
            dep_version = match.group(2)
            
            # Skip ignored dependencies
            if dep_name in ignored_deps:
                continue
            
            try:
                dependency = Dependency(dep_name, dep_version)
                dependencies.append(dependency)
            except ValueError as e:
                print(f"Warning: Invalid dependency version '{dep_version}' for '{dep_name}' in {module_bazel_path}: {e}")
        
    except Exception as e:
        print(f"Error reading {module_bazel_path}: {e}")
    
    return module_name, module_version, dependencies