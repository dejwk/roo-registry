#!/usr/bin/env python3
"""
Shared utilities for working with roo modules and their dependencies.
"""

import os
import re
from typing import List, Tuple, Dict, Set
from pathlib import Path


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