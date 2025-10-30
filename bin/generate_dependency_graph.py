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
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import Version, Dependency, parse_module_bazel


def get_modules_and_versions(modules_dir: Path) -> Dict[str, List[Version]]:
    """
    Get all modules and their versions from the modules directory.
    Returns a dict mapping module name to list of versions.
    """
    modules = {}
    
    if not modules_dir.exists():
        return modules
    
    for module_path in modules_dir.iterdir():
        if module_path.is_dir() and module_path.name.startswith('roo_'):
            module_name = module_path.name
            versions = []
            
            for version_path in module_path.iterdir():
                if version_path.is_dir():
                    try:
                        version = Version(version_path.name)
                        versions.append(version)
                    except ValueError:
                        # Skip invalid version directories
                        continue
            
            if versions:
                modules[module_name] = sorted(versions, reverse=True)
    
    return modules


def get_untracked_modules(registry_dir: Path, registry_modules: Dict[str, List[Version]]) -> Dict[str, Version]:
    """
    Get all untracked roo_* directories that are not in the registry.
    Returns a dict mapping module name to its version from MODULE.bazel or library.json.
    """
    untracked = {}
    parent_dir = registry_dir.parent
    
    if not parent_dir.exists():
        return untracked
    
    for untracked_path in parent_dir.iterdir():
        if (untracked_path.is_dir() and 
            untracked_path.name.startswith('roo_') and 
            untracked_path != registry_dir and
            untracked_path.name not in registry_modules):  # Only include if NOT in registry
            
            module_bazel_path = untracked_path / "MODULE.bazel"
            library_json_path = untracked_path / "library.json"
            
            # Try MODULE.bazel first
            if module_bazel_path.exists():
                try:
                    module_name, version_str, _ = parse_module_bazel(module_bazel_path)
                    if version_str:
                        version = Version(version_str)
                        untracked[untracked_path.name] = version
                        continue
                except Exception as e:
                    print(f"Warning: Failed to parse {module_bazel_path}: {e}")
            
            # Fall back to library.json
            if library_json_path.exists():
                try:
                    import json
                    with open(library_json_path, 'r') as f:
                        library_data = json.load(f)
                    
                    version_str = library_data.get('version')
                    if version_str:
                        version = Version(version_str)
                        untracked[untracked_path.name] = version
                        print(f"Note: {untracked_path.name} uses library.json version (no MODULE.bazel)")
                        continue
                except Exception as e:
                    print(f"Warning: Failed to parse {library_json_path}: {e}")
            
            # If we get here, the module has no parseable version info
            print(f"Warning: {untracked_path.name} has no MODULE.bazel or library.json with version")
    
    return untracked


def get_untracked_dependencies(registry_dir: Path, untracked_modules: Dict[str, Version]) -> Dict[str, List[Dependency]]:
    """
    Get dependencies for all untracked modules.
    Returns a dict mapping module name to list of dependencies.
    """
    all_deps = {}
    parent_dir = registry_dir.parent
    
    for module_name in untracked_modules:
        untracked_path = parent_dir / module_name
        module_bazel_path = untracked_path / "MODULE.bazel"
        library_json_path = untracked_path / "library.json"
        
        dependencies = []
        
        # Try MODULE.bazel first
        if module_bazel_path.exists():
            try:
                _, _, dependencies = parse_module_bazel(module_bazel_path)
            except Exception as e:
                print(f"Warning: Failed to parse dependencies from {module_bazel_path}: {e}")
        
        # Fall back to library.json if no MODULE.bazel or no dependencies found
        if not dependencies and library_json_path.exists():
            try:
                import json
                with open(library_json_path, 'r') as f:
                    library_data = json.load(f)
                
                deps_dict = library_data.get('dependencies', {})
                for dep_name, version_constraint in deps_dict.items():
                    # Convert "dejwk/module_name" to "module_name"
                    if '/' in dep_name:
                        clean_name = dep_name.split('/')[-1]
                    else:
                        clean_name = dep_name
                    
                    # Parse version constraint (e.g., ">0", ">=1.0.0")
                    # For simplicity, we'll use a minimum version for constraint-only deps
                    if version_constraint.startswith('>='):
                        version_str = version_constraint[2:]
                    elif version_constraint.startswith('>'):
                        version_part = version_constraint[1:]
                        if version_part == '0':
                            version_str = '0.0.1'  # Use minimum version for ">0"
                        else:
                            version_str = version_part
                    elif version_constraint.startswith('='):
                        version_str = version_constraint[1:]
                    else:
                        version_str = version_constraint
                    
                    # Handle special cases
                    if version_str in ['0', '']:
                        version_str = '0.0.1'  # Use minimum version for "0" or empty
                    
                    try:
                        version = Version(version_str)
                        dependency = Dependency(clean_name, version)
                        dependencies.append(dependency)
                    except Exception as e:
                        # For ">0" and similar constraints, skip the dependency rather than warn
                        # since these are often just "any version" constraints
                        if version_constraint not in ['>0', '>=0', '>0.0', '>=0.0']:
                            print(f"Warning: Could not parse version '{version_constraint}' for dependency '{clean_name}' in {module_name}: {e}")
                        continue
            except Exception as e:
                print(f"Warning: Failed to parse dependencies from {library_json_path}: {e}")
        
        all_deps[module_name] = dependencies
    
    return all_deps


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


def check_git_dirty_status(module_name: str, module_version: str, base_dir: Path) -> bool:
    """
    Check if a module's git repository is dirty.
    
    A module is considered dirty if:
    1. It has uncommitted changes, OR
    2. It has committed changes since the last tag, OR  
    3. The latest commit doesn't match the tag for the current version
    
    Returns True if dirty, False if clean.
    """
    try:
        # Use the provided base directory to find modules
        current_dir = base_dir
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
            # Any changes in git status indicate dirty repository
            lines = status_output.split('\n')
            significant_changes = [line for line in lines if line.strip()]
            
            if significant_changes:
                return True  # Has uncommitted changes
        
        # Check 2 & 3: Compare HEAD with tag
        version_tag = module_version  # Use semver format (x.y.z)
        
        # Get the commit hash of the current HEAD
        head_commit = run_git_command(["rev-parse", "HEAD"])
        if not head_commit:
            return True  # Can't determine HEAD, assume dirty
        
        # Get the commit hash of the version tag
        tag_commit = run_git_command(["rev-parse", f"{version_tag}^{{commit}}"])
        if not tag_commit:
            # Tag doesn't exist, assume dirty
            return True
        
        # Compare commits
        if head_commit != tag_commit:
            return True  # HEAD is different from tag
        
        return False  # Clean
        
    except Exception as e:
        # If any error occurs, assume not dirty (don't want git issues to break the graph)
        print(f"Warning: Could not check git status for {module_name}: {e}")
        return False


def get_all_dirty_statuses(newest_versions: Dict[str, Version], 
                          untracked_modules: Dict[str, Version], base_dir: Path) -> Dict[str, bool]:
    """
    Check git dirty status for all modules (registry and untracked).
    
    Returns a dictionary mapping module names to their dirty status.
    """
    dirty_statuses = {}
    
    print("Checking git status for modules...")
    
    # Check registry modules
    for module_name, version in newest_versions.items():
        is_dirty = check_git_dirty_status(module_name, str(version), base_dir)
        dirty_statuses[module_name] = is_dirty
        if is_dirty:
            print(f"  {module_name}: DIRTY")
        else:
            print(f"  {module_name}: clean")
    
    # Check untracked modules
    for module_name, version in untracked_modules.items():
        is_dirty = check_git_dirty_status(module_name, str(version), base_dir)
        dirty_statuses[module_name] = is_dirty
        if is_dirty:
            print(f"  {module_name} (untracked): DIRTY")
        else:
            print(f"  {module_name} (untracked): clean")
    
    return dirty_statuses


def generate_dot_file(output_path: Path, newest_versions: Dict[str, Version], 
                     all_dependencies: Dict[str, List[Dependency]], 
                     dirty_statuses: Dict[str, bool],
                     untracked_modules: Dict[str, Version]) -> bool:
    """
    Generate a DOT file for the dependency graph and create SVG output.
    """
    try:
        # Create the doc directory if it doesn't exist
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Combine registry and untracked modules for processing
        all_modules = dict(newest_versions)
        all_modules.update(untracked_modules)
        
        # Find redundant dependencies to remove
        redundant_deps = find_redundant_dependencies(all_dependencies, all_modules)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write('digraph dependencies {\n')
            f.write('    rankdir=TB;\n')
            f.write('    node [shape=box, style=filled];\n')
            f.write('    edge [fontsize=10];\n\n')
            
            # Write nodes (modules)
            f.write('    // Modules\n')
            for module_name in sorted(all_modules.keys()):
                version = all_modules[module_name]
                label = f"{module_name}\\n{version}"
                
                # Choose node color based on dirty status and type
                is_dirty = dirty_statuses.get(module_name, False)
                is_untracked = module_name in untracked_modules
                
                if is_untracked:
                    if is_dirty:
                        color = "plum"         # Pinkish-purple for dirty untracked modules
                    else:
                        color = "mistyrose"    # Light pink for clean untracked modules
                else:
                    if is_dirty:
                        color = "khaki"        # Khaki for dirty registry modules
                    else:
                        color = "#b1dbab"      # Custom light green for clean registry modules
                
                f.write(f'    "{module_name}" [label="{label}", fillcolor="{color}"];\n')
            
            f.write('\n    // Dependencies\n')
            
            # Write edges (dependencies)
            for module_name in sorted(all_dependencies.keys()):
                dependencies = all_dependencies[module_name]
                checked_deps = check_dependency_versions(dependencies, all_modules)
                
                for dep, is_latest in checked_deps:
                    # Only include roo modules in the graph
                    if dep.name not in all_modules:
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
                            latest_version = all_modules[dep.name]
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
    
    # Get all modules and their versions from registry
    modules = get_modules_and_versions(modules_dir)
    
    if not modules:
        print("No modules found or no valid versions detected.")
        return False
    
    # Find newest versions from registry
    newest_versions = find_newest_versions(modules)
    
    # Get untracked modules (roo_* directories outside registry, not in registry)
    untracked_modules = get_untracked_modules(registry_dir, modules)
    
    # Get dependencies for all newest versions (only from registry modules)
    all_dependencies = get_all_dependencies(modules_dir, newest_versions)
    
    # Get dependencies for untracked modules
    untracked_dependencies = get_untracked_dependencies(registry_dir, untracked_modules)
    
    # Combine all dependencies
    all_dependencies.update(untracked_dependencies)
    
    # Check git dirty status for all modules (registry + untracked)
    dirty_statuses = get_all_dirty_statuses(newest_versions, untracked_modules, registry_dir.parent)
    
    # Calculate counts
    total_modules = len(newest_versions) + len(untracked_modules)
    dirty_count = sum(1 for is_dirty in dirty_statuses.values() if is_dirty)
    
    print(f"\nFound {len(newest_versions)} registry modules:")
    for module_name in sorted(newest_versions.keys()):
        version = newest_versions[module_name]
        dep_count = len([dep for dep in all_dependencies.get(module_name, []) 
                        if dep.name in newest_versions or dep.name in untracked_modules])
        is_dirty = dirty_statuses.get(module_name, False)
        status = "DIRTY" if is_dirty else "clean"
        print(f"  {module_name} v{version} ({dep_count} roo dependencies) - {status}")
    
    if untracked_modules:
        print(f"\nFound {len(untracked_modules)} untracked modules:")
        for module_name in sorted(untracked_modules.keys()):
            version = untracked_modules[module_name]
            is_dirty = dirty_statuses.get(module_name, False)
            status = "DIRTY" if is_dirty else "clean"
            print(f"  {module_name} v{version} (untracked) - {status}")
    
    print(f"\nSummary: {dirty_count} dirty modules, {total_modules - dirty_count} clean modules")
    
    # Generate DOT file
    if generate_dot_file(output_path, newest_versions, all_dependencies, dirty_statuses, untracked_modules):
        print(f"\n✓ Successfully generated dependency graph: {output_path}")
        
        # Check if SVG was generated
        svg_path = output_path.with_suffix('.svg')
        if svg_path.exists():
            print(f"✓ Also generated SVG visualization: {svg_path}")
        
        print(f"\nNode colors:")
        print(f"  Light green (#b1dbab): Clean registry modules (git status matches latest tag)")
        print(f"  Khaki: Dirty registry modules (uncommitted changes or commits since tag)")
        print(f"  Misty rose: Clean untracked modules")
        print(f"  Plum: Dirty untracked modules")
        print(f"  Red edges: Outdated dependencies")
        return True
    else:
        print(f"\n✗ Failed to generate dependency graph")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)