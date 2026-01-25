#!/usr/bin/env python3
"""
Shared utilities for working with roo modules and their dependencies.
"""

import os
import re
from typing import List, Tuple, Dict, Set, Optional
from pathlib import Path

# Check for GitPython availability
try:
    import git
except ImportError:
    raise ImportError(
        "GitPython is required but not installed.\n"
        "Install it with: pip install GitPython"
    )


def get_git_status(repo_path: Path) -> Tuple[bool, List[str]]:
    """
    Check if repository has uncommitted changes.
    Returns (has_changes, list_of_changes).
    """
    try:
        repo = git.Repo(repo_path)
        
        # Check for dirty files (modified, staged, untracked)
        changes = []
        
        # Modified files
        for item in repo.index.diff(None):
            changes.append(f"M  {item.a_path}")
        
        # Staged files
        for item in repo.index.diff("HEAD"):
            changes.append(f"A  {item.a_path}")
        
        # Untracked files
        for file in repo.untracked_files:
            changes.append(f"?? {file}")
        
        return len(changes) > 0, changes
    except Exception as e:
        return False, [f"Error checking git status: {str(e)}"]


def get_current_branch(repo_path: Path) -> Tuple[bool, str]:
    """
    Get the current branch name.
    Returns (success, branch_name_or_error_msg).
    """
    try:
        repo = git.Repo(repo_path)
        if repo.head.is_detached:
            return False, "Not on any branch (detached HEAD)"
        return True, repo.active_branch.name
    except Exception as e:
        return False, f"Could not determine current branch: {str(e)}"


def get_upstream_branch(repo_path: Path, branch: str) -> Tuple[bool, str]:
    """
    Get the upstream branch for the given branch.
    Returns (success, upstream_branch_or_error_msg).
    """
    try:
        repo = git.Repo(repo_path)
        branch_obj = repo.heads[branch]
        
        if branch_obj.tracking_branch() is None:
            return False, f"No upstream branch configured for {branch}"
        
        upstream = branch_obj.tracking_branch().name
        return True, upstream
    except Exception as e:
        return False, f"Could not get upstream branch: {str(e)}"


def count_commits_between(repo_path: Path, base: str, head: str) -> Tuple[bool, int, str]:
    """
    Count commits between two references.
    Returns (success, commit_count, error_msg_if_failed).
    """
    try:
        repo = git.Repo(repo_path)
        commits = list(repo.iter_commits(f"{base}..{head}"))
        return True, len(commits), ""
    except Exception as e:
        return False, 0, str(e)


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
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin
        
        # Fetch to get latest remote info
        origin.fetch()
        
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
    except Exception as e:
        return False, f"Could not fetch from remote: {str(e)}"


def git_push(repo_path: Path) -> Tuple[bool, str]:
    """Push commits to remote. Returns (success, message)."""
    try:
        repo = git.Repo(repo_path)
        origin = repo.remotes.origin
        current_branch = repo.active_branch.name
        
        # Push current branch to origin
        push_infos = origin.push(current_branch)
        
        # Check for errors in push results
        for push_info in push_infos:
            if push_info.flags & push_info.ERROR:
                return False, f"Push failed: {push_info.summary}"
        
        return True, "Successfully pushed"
    except Exception as e:
        return False, f"Push failed: {str(e)}"


def git_pull_rebase(repo_path: Path) -> Tuple[bool, str]:
    """Pull with rebase from remote. Returns (success, message)."""
    try:
        repo = git.Repo(repo_path)
        
        # Pull with rebase (equivalent to 'git pull --rebase')
        repo.git.pull('--rebase')
        return True, "Successfully pulled with rebase"
    except Exception as e:
        return False, f"Pull rebase failed: {str(e)}"


def git_clone(repo_url: str, target_path: Path, timeout: int = 60) -> Tuple[bool, str]:
    """Clone a repository from GitHub. Returns (success, message)."""
    try:
        git.Repo.clone_from(repo_url, str(target_path))
        return True, "Successfully cloned"
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