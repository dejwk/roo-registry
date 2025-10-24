#!/usr/bin/env python3
"""
Script to generate a dependencies.dot file for visualizing the roo module dependency graph.

Usage: python3 roo-registry/bin/generate_dependency_graph.py

This script should be run from the parent directory of roo-registry.
It will create a DOT file at roo-registry/doc/dependencies.dot that shows:
- Modules as nodes with name and newest version
- Dependencies as directed edges
- Outdated dependencies in red
- Transitive dependencies are removed unless they represent outdated dependencies
"""

import sys
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import Version, Dependency, parse_module_bazel


def get_modules_and_versions(modules_dir: Path) -> Dict[str, List[Version]]:
    """
    Scan the modules directory and return a dictionary mapping module names 
    to lists of their available versions.
    """
    modules = {}
    
    if not modules_dir.exists():
        print(f"Warning: Modules directory '{modules_dir}' does not exist.")
        return modules
    
    if not modules_dir.is_dir():
        print(f"Warning: '{modules_dir}' is not a directory.")
        return modules
    
    # Iterate through each subdirectory (module) in the modules directory
    for module_path in modules_dir.iterdir():
        if not module_path.is_dir():
            continue
        
        module_name = module_path.name
        versions = []
        
        # Iterate through each subdirectory (version) in the module directory
        for version_path in module_path.iterdir():
            if not version_path.is_dir():
                continue
            
            version_str = version_path.name
            try:
                version = Version(version_str)
                versions.append(version)
            except ValueError as e:
                print(f"Warning: Skipping invalid version '{version_str}' for module '{module_name}': {e}")
                continue
        
        if versions:
            # Sort versions to make it easier to find the newest
            versions.sort()
            modules[module_name] = versions
    
    return modules


def find_newest_versions(modules: Dict[str, List[Version]]) -> Dict[str, Version]:
    """
    Given a dictionary of modules and their versions, return a dictionary 
    mapping module names to their newest version.
    """
    newest_versions = {}
    
    for module_name, versions in modules.items():
        if versions:
            # Get the highest version (last in sorted list)
            newest_versions[module_name] = max(versions)
    
    return newest_versions


def get_module_dependencies(modules_dir: Path, module_name: str, version: Version) -> List[Dependency]:
    """
    Get the dependencies for a specific module version by parsing its MODULE.bazel file.
    """
    module_bazel_path = modules_dir / module_name / str(version) / "MODULE.bazel"
    _, _, dependencies = parse_module_bazel(module_bazel_path)
    return dependencies


def get_all_dependencies(modules_dir: Path, newest_versions: Dict[str, Version]) -> Dict[str, List[Dependency]]:
    """
    Get dependencies for all modules' newest versions.
    
    Returns a dictionary mapping module names to their list of dependencies.
    """
    all_dependencies = {}
    
    for module_name, version in newest_versions.items():
        dependencies = get_module_dependencies(modules_dir, module_name, version)
        all_dependencies[module_name] = dependencies
    
    return all_dependencies


def check_dependency_versions(dependencies: List[Dependency], newest_versions: Dict[str, Version]) -> List[Tuple[Dependency, bool]]:
    """
    Check if dependencies are using the most recent versions.
    
    Returns a list of tuples (dependency, is_latest) where is_latest indicates
    if the dependency is using the most recent version available.
    """
    checked_dependencies = []
    
    for dep in dependencies:
        # Check if this dependency is a module in our repository
        if dep.name in newest_versions:
            latest_version = newest_versions[dep.name]
            is_latest = dep.version == latest_version
        else:
            # External dependency - we can't check if it's latest
            is_latest = True  # Assume external deps are fine
        
        checked_dependencies.append((dep, is_latest))
    
    return checked_dependencies


def find_redundant_dependencies(all_dependencies: Dict[str, List[Dependency]], newest_versions: Dict[str, Version]) -> Set[Tuple[str, str]]:
    """
    Find redundant dependencies that can be removed from the graph.
    
    A dependency A -> B is redundant if:
    1. The dependency A -> B is up-to-date (not outdated), AND
    2. There exists a path from A to B through other up-to-date dependencies
    
    Returns a set of tuples (from_module, to_module) representing redundant dependencies.
    """
    redundant_deps = set()
    
    def has_path_through_updated_deps(start: str, target: str, original_start: str, visited: Set[str]) -> bool:
        """
        Check if there's a path from start to target using only up-to-date dependencies.
        original_start is used to identify the direct edge we want to exclude.
        """
        if start in visited:
            return False
        
        visited.add(start)
        
        # Get dependencies of the current module
        deps = all_dependencies.get(start, [])
        
        for dep in deps:
            # Only consider roo modules
            if dep.name not in newest_versions:
                continue
            
            # Skip the direct edge we're testing for redundancy
            if start == original_start and dep.name == target:
                continue
            
            # Check if this dependency is up-to-date
            latest_version = newest_versions[dep.name]
            is_up_to_date = dep.version == latest_version
            
            if is_up_to_date:
                # If we reached the target, we found a path
                if dep.name == target:
                    return True
                
                # Recursively check if we can reach target from this dependency
                if has_path_through_updated_deps(dep.name, target, original_start, visited.copy()):
                    return True
        
        return False
    
    # Check each direct dependency to see if it's redundant
    for module in all_dependencies:
        dependencies = all_dependencies[module]
        checked_deps = check_dependency_versions(dependencies, newest_versions)
        
        for dep, is_latest in checked_deps:
            # Only consider roo modules
            if dep.name not in newest_versions:
                continue
            
            # Only check up-to-date dependencies for redundancy
            if is_latest:
                # Check if there's an alternative path through other up-to-date dependencies
                # excluding the direct edge we're testing
                if has_path_through_updated_deps(module, dep.name, module, set()):
                    redundant_deps.add((module, dep.name))
    
    return redundant_deps


def check_git_dirty_status(module_name: str, module_version: str) -> bool:
    """
    Check if a module's git repository is dirty.
    
    A module is considered dirty if:
    1. It has uncommitted changes, OR
    2. It has committed changes since the last tag, OR  
    3. The latest commit doesn't match the tag for the current version
    
    Returns True if dirty, False if clean.
    """
    try:
        # Get the current working directory (parent of roo-registry)
        current_dir = Path.cwd()
        module_dir = current_dir / module_name
        
        if not module_dir.exists() or not (module_dir / ".git").exists():
            # If module directory or .git doesn't exist, assume not dirty
            return False
        
        # Change to module directory for git commands
        def run_git_command(cmd: List[str]) -> str:
            """Run git command in module directory and return output."""
            result = subprocess.run(
                ["git"] + cmd,
                cwd=module_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                return ""
            return result.stdout.strip()
        
        # Check 1: Uncommitted changes (working directory dirty)
        status_output = run_git_command(["status", "--porcelain"])
        if status_output:
            # Filter out ignored files
            lines = status_output.split('\n')
            significant_changes = []
            
            for line in lines:
                if not line.strip():
                    continue
                
                # Extract filename from git status line
                # Format: "XY filename" where X and Y are status codes
                if len(line) >= 3:
                    filename = line[3:].strip()
                    
                    # Ignore MODULE.bazel.lock and bazel-* symlinks
                    if filename == "MODULE.bazel.lock":
                        continue
                    if filename.startswith("bazel-"):
                        continue
                    
                    significant_changes.append(line)
            
            if significant_changes:
                return True  # Has significant uncommitted changes
        
        # Check 2 & 3: Compare HEAD with tag
        version_tag = module_version  # Try without 'v' prefix first
        
        # Get the commit hash of the current HEAD
        head_commit = run_git_command(["rev-parse", "HEAD"])
        if not head_commit:
            return True  # Can't determine HEAD, assume dirty
        
        # Try to get the commit hash of the version tag (try without 'v' first, then with 'v')
        tag_commit = run_git_command(["rev-parse", f"{version_tag}^{{commit}}"])
        if not tag_commit:
            # Try with 'v' prefix
            version_tag = f"v{module_version}"
            tag_commit = run_git_command(["rev-parse", f"{version_tag}^{{commit}}"])
            if not tag_commit:
                # Tag doesn't exist in either format, assume dirty
                return True
        
        # Compare commits
        if head_commit != tag_commit:
            return True  # HEAD is different from tag
        
        return False  # Clean
        
    except Exception as e:
        # If any error occurs, assume not dirty (don't want git issues to break the graph)
        print(f"Warning: Could not check git status for {module_name}: {e}")
        return False


def get_all_dirty_statuses(newest_versions: Dict[str, Version]) -> Dict[str, bool]:
    """
    Check git dirty status for all modules.
    
    Returns a dictionary mapping module names to their dirty status.
    """
    dirty_statuses = {}
    
    print("Checking git status for modules...")
    for module_name, version in newest_versions.items():
        is_dirty = check_git_dirty_status(module_name, str(version))
        dirty_statuses[module_name] = is_dirty
        if is_dirty:
            print(f"  {module_name}: DIRTY")
        else:
            print(f"  {module_name}: clean")
    
    return dirty_statuses


def generate_dot_file(output_path: Path, newest_versions: Dict[str, Version], 
                     all_dependencies: Dict[str, List[Dependency]], 
                     dirty_statuses: Dict[str, bool]) -> bool:
    """
    Generate a DOT file for the dependency graph and create SVG output.
    """
    try:
        # Create the doc directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Find redundant dependencies to remove
        redundant_deps = find_redundant_dependencies(all_dependencies, newest_versions)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('digraph dependencies {\n')
            f.write('    rankdir=TB;\n')
            f.write('    node [shape=box, style=filled];\n')
            f.write('    edge [fontsize=10];\n\n')
            
            # Write nodes (modules)
            f.write('    // Modules\n')
            for module_name in sorted(newest_versions.keys()):
                version = newest_versions[module_name]
                label = f"{module_name}\\n{version}"
                
                # Choose node color based on dirty status
                is_dirty = dirty_statuses.get(module_name, False)
                if is_dirty:
                    color = "lightyellow"  # Yellowish tint for dirty modules
                else:
                    color = "lightblue"    # Default color for clean modules
                
                f.write(f'    "{module_name}" [label="{label}", fillcolor="{color}"];\n')
            
            f.write('\n    // Dependencies\n')
            
            # Write edges (dependencies)
            for module_name in sorted(all_dependencies.keys()):
                dependencies = all_dependencies[module_name]
                checked_deps = check_dependency_versions(dependencies, newest_versions)
                
                for dep, is_latest in checked_deps:
                    # Only include roo modules in the graph
                    if dep.name not in newest_versions:
                        continue
                    
                    # Check if this dependency is redundant
                    is_redundant = (module_name, dep.name) in redundant_deps
                    
                    # Include edge if:
                    # 1. It's not redundant, OR
                    # 2. It's outdated (even if redundant, we want to highlight outdated deps)
                    if not is_redundant or not is_latest:
                        if is_latest:
                            # Up-to-date dependency
                            f.write(f'    "{module_name}" -> "{dep.name}";\n')
                        else:
                            # Outdated dependency - use red color
                            latest_version = newest_versions[dep.name]
                            label = f"{dep.version}\\n(latest: {latest_version})"
                            f.write(f'    "{module_name}" -> "{dep.name}" [color=red, fontcolor=red, label="{label}"];\n')
            
            f.write('}\n')
        
        # Generate SVG file using dot command
        svg_path = output_path.with_suffix('.svg')
        try:
            result = subprocess.run(
                ["dot", "-Tsvg", str(output_path), "-o", str(svg_path)],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode == 0:
                print(f"✓ Generated SVG file: {svg_path}")
            else:
                print(f"Warning: Failed to generate SVG file. dot command error: {result.stderr}")
        except FileNotFoundError:
            print(f"Warning: 'dot' command not found. Please install Graphviz to generate SVG files.")
        except subprocess.TimeoutExpired:
            print(f"Warning: SVG generation timed out.")
        except Exception as e:
            print(f"Warning: Failed to generate SVG file: {e}")
        
        return True
        
    except Exception as e:
        print(f"Error writing DOT file: {e}")
        return False


def main():
    """Main function."""
    # Get the script directory and find the roo-registry directory
    script_dir = Path(__file__).parent
    registry_dir = script_dir.parent
    modules_dir = registry_dir / "modules"
    output_path = registry_dir / "doc" / "dependencies.dot"
    
    print(f"Scanning modules directory: {modules_dir}")
    print(f"Output DOT file: {output_path}")
    
    # Get all modules and their versions
    modules = get_modules_and_versions(modules_dir)
    
    if not modules:
        print("No modules found or no valid versions detected.")
        return False
    
    # Find newest versions
    newest_versions = find_newest_versions(modules)
    
    # Get dependencies for all newest versions
    all_dependencies = get_all_dependencies(modules_dir, newest_versions)
    
    # Check git dirty status for all modules
    dirty_statuses = get_all_dirty_statuses(newest_versions)
    
    print(f"\nFound {len(newest_versions)} modules:")
    dirty_count = sum(1 for is_dirty in dirty_statuses.values() if is_dirty)
    for module_name in sorted(newest_versions.keys()):
        version = newest_versions[module_name]
        dep_count = len([dep for dep in all_dependencies.get(module_name, []) 
                        if dep.name in newest_versions])
        is_dirty = dirty_statuses.get(module_name, False)
        status = "DIRTY" if is_dirty else "clean"
        print(f"  {module_name} v{version} ({dep_count} roo dependencies) - {status}")
    
    print(f"\nSummary: {dirty_count} dirty modules, {len(newest_versions) - dirty_count} clean modules")
    
    # Generate DOT file
    if generate_dot_file(output_path, newest_versions, all_dependencies, dirty_statuses):
        print(f"\n✓ Successfully generated dependency graph: {output_path}")
        
        # Check if SVG was generated
        svg_path = output_path.with_suffix('.svg')
        if svg_path.exists():
            print(f"✓ Also generated SVG visualization: {svg_path}")
        
        print(f"\nNode colors:")
        print(f"  Light blue: Clean modules (git status matches latest tag)")
        print(f"  Light yellow: Dirty modules (uncommitted changes or commits since tag)")
        print(f"  Red edges: Outdated dependencies")
        return True
    else:
        print(f"\n✗ Failed to generate dependency graph")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)