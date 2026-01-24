#!/usr/bin/env python3
"""
Script to generate a dependencies.dot file for visualizing the roo module dependency graph.

Usage: python3 roo-registry/bin/generate_dependency_graph.py [--show_outdated]

This script should be run from the parent directory of roo-registry.
It will create a DOT file at roo-registry/doc/dependencies.dot that shows:
- Modules as nodes with name and newest version
- Dependencies as directed edges
- Outdated dependencies in red
- Transitive dependencies are removed (unless --show_outdated is specified)
- Modules with outdated dependencies have red outlines (when --show_outdated is not specified)
"""

import sys
import subprocess
import json
import argparse
from pathlib import Path
from typing import Dict, List, Set, Tuple

# Check for GitPython availability
try:
    import git
except ImportError:
    raise ImportError(
        "GitPython is required but not installed.\n"
        "Install it with: pip install GitPython"
    )

# Configuration: Modules to ignore in dependency analysis
# Add module names to this list to exclude them from the dependency graph
IGNORED_MODULES = [
    "roo_io_arduino",
    # Add more modules here as needed, one per line
    # Example: 'another_module_to_ignore',
]

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import Version, Dependency, parse_module_bazel


def should_ignore_module(module_name: str) -> bool:
    """Check if a module should be ignored based on the IGNORED_MODULES list."""
    # Extract the actual module name from various formats
    clean_name = module_name

    # Remove path prefixes if present
    if "/" in clean_name:
        clean_name = clean_name.split("/")[-1]

    # Check if the module name matches any ignored module
    return clean_name in IGNORED_MODULES


def get_modules_and_versions(modules_dir: Path) -> Dict[str, List[Version]]:
    """
    Get all modules and their versions from the modules directory.
    Returns a dict mapping module name to list of versions.
    """
    modules = {}

    if not modules_dir.exists():
        return modules

    for module_path in modules_dir.iterdir():
        if module_path.is_dir() and module_path.name.startswith("roo_"):
            module_name = module_path.name

            # Skip ignored modules
            if should_ignore_module(module_name):
                print(f"Ignoring module: {module_name}")
                continue

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


def get_untracked_modules(
    registry_dir: Path, registry_modules: Dict[str, List[Version]]
) -> Dict[str, Version]:
    """
    Get all untracked roo_* directories that are not in the registry.
    Returns a dict mapping module name to its version from MODULE.bazel or library.json.
    """
    untracked = {}
    parent_dir = registry_dir.parent

    if not parent_dir.exists():
        return untracked

    for untracked_path in parent_dir.iterdir():
        if (
            untracked_path.is_dir()
            and untracked_path.name.startswith("roo_")
            and untracked_path != registry_dir
            and untracked_path.name not in registry_modules
        ):  # Only include if NOT in registry

            # Skip ignored modules
            if should_ignore_module(untracked_path.name):
                print(f"Ignoring untracked module: {untracked_path.name}")
                continue

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

                    with open(library_json_path, "r") as f:
                        library_data = json.load(f)

                    version_str = library_data.get("version")
                    if version_str:
                        version = Version(version_str)
                        untracked[untracked_path.name] = version
                        print(
                            f"Note: {untracked_path.name} uses library.json version (no MODULE.bazel)"
                        )
                        continue
                except Exception as e:
                    print(f"Warning: Failed to parse {library_json_path}: {e}")

            # If we get here, the module has no parseable version info
            print(
                f"Warning: {untracked_path.name} has no MODULE.bazel or library.json with version"
            )

    return untracked


def get_untracked_dependencies(
    registry_dir: Path, untracked_modules: Dict[str, Version]
) -> Dict[str, List[Dependency]]:
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
                print(
                    f"Warning: Failed to parse dependencies from {module_bazel_path}: {e}"
                )

        # Fall back to library.json if no MODULE.bazel or no dependencies found
        if not dependencies and library_json_path.exists():
            try:
                import json

                with open(library_json_path, "r") as f:
                    library_data = json.load(f)

                deps_dict = library_data.get("dependencies", {})
                for dep_name, version_constraint in deps_dict.items():
                    # Convert "dejwk/module_name" to "module_name"
                    if "/" in dep_name:
                        clean_name = dep_name.split("/")[-1]
                    else:
                        clean_name = dep_name

                    # Skip ignored modules
                    if should_ignore_module(clean_name):
                        print(
                            f"Filtering out ignored dependency: {clean_name} from {module_name}"
                        )
                        continue

                    # Parse version constraint (e.g., ">0", ">=1.0.0")
                    # For simplicity, we'll use a minimum version for constraint-only deps
                    if version_constraint.startswith(">="):
                        version_str = version_constraint[2:]
                    elif version_constraint.startswith(">"):
                        version_part = version_constraint[1:]
                        if version_part == "0":
                            version_str = "0.0.1"  # Use minimum version for ">0"
                        else:
                            version_str = version_part
                    elif version_constraint.startswith("="):
                        version_str = version_constraint[1:]
                    else:
                        version_str = version_constraint

                    # Handle special cases
                    if version_str in ["0", ""]:
                        version_str = "0.0.1"  # Use minimum version for "0" or empty

                    try:
                        version = Version(version_str)
                        dependency = Dependency(clean_name, version)
                        dependencies.append(dependency)
                    except Exception as e:
                        # For ">0" and similar constraints, skip the dependency rather than warn
                        # since these are often just "any version" constraints
                        if version_constraint not in [">0", ">=0", ">0.0", ">=0.0"]:
                            print(
                                f"Warning: Could not parse version '{version_constraint}' for dependency '{clean_name}' in {module_name}: {e}"
                            )
                        continue
            except Exception as e:
                print(
                    f"Warning: Failed to parse dependencies from {library_json_path}: {e}"
                )

        # Filter out ignored modules from the final dependencies list
        filtered_dependencies = []
        for dep in dependencies:
            if not should_ignore_module(dep.name):
                filtered_dependencies.append(dep)
            else:
                print(
                    f"Filtering out ignored dependency: {dep.name} from {module_name}"
                )

        all_deps[module_name] = filtered_dependencies

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


def get_module_dependencies(
    modules_dir: Path, module_name: str, version: Version
) -> List[Dependency]:
    """
    Get the dependencies for a specific module version by parsing its MODULE.bazel file.
    """
    module_bazel_path = modules_dir / module_name / str(version) / "MODULE.bazel"
    _, _, dependencies = parse_module_bazel(module_bazel_path)

    # Filter out ignored modules from dependencies
    filtered_dependencies = []
    for dep in dependencies:
        if not should_ignore_module(dep.name):
            filtered_dependencies.append(dep)
        else:
            print(f"Filtering out ignored dependency: {dep.name} from {module_name}")

    return filtered_dependencies


def get_all_dependencies(
    modules_dir: Path, newest_versions: Dict[str, Version]
) -> Dict[str, List[Dependency]]:
    """
    Get dependencies for all modules' newest versions.

    Returns a dictionary mapping module names to their list of dependencies.
    """
    all_dependencies = {}

    for module_name, version in newest_versions.items():
        dependencies = get_module_dependencies(modules_dir, module_name, version)
        all_dependencies[module_name] = dependencies

    return all_dependencies


def check_dependency_versions(
    dependencies: List[Dependency], newest_versions: Dict[str, Version]
) -> List[Tuple[Dependency, bool]]:
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


def find_modules_with_outdated_deps(
    all_dependencies: Dict[str, List[Dependency]], newest_versions: Dict[str, Version]
) -> Set[str]:
    """
    Find all modules that have at least one outdated dependency.
    
    Returns a set of module names that have outdated dependencies.
    """
    modules_with_outdated = set()
    
    for module in all_dependencies:
        dependencies = all_dependencies[module]
        checked_deps = check_dependency_versions(dependencies, newest_versions)
        
        for dep, is_latest in checked_deps:
            # Only consider roo modules
            if dep.name not in newest_versions:
                continue
            
            # If we find any outdated dependency, mark this module
            if not is_latest:
                modules_with_outdated.add(module)
                break  # No need to check other dependencies
    
    return modules_with_outdated


def find_redundant_dependencies(
    all_dependencies: Dict[str, List[Dependency]], 
    newest_versions: Dict[str, Version],
    keep_outdated: bool = False
) -> Set[Tuple[str, str]]:
    """
    Find redundant dependencies that can be removed from the graph.

    A dependency A -> B is redundant if:
    1. (If keep_outdated=False) There exists a path from A to B through other dependencies, OR
    2. (If keep_outdated=True) The dependency A -> B is up-to-date AND there exists a path 
       from A to B through other up-to-date dependencies

    Returns a set of tuples (from_module, to_module) representing redundant dependencies.
    """
    redundant_deps = set()

    def has_path_through_deps(
        start: str, target: str, original_start: str, visited: Set[str], only_updated: bool
    ) -> bool:
        """
        Check if there's a path from start to target.
        If only_updated is True, use only up-to-date dependencies.
        If only_updated is False, use any dependencies.
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

            # If we require only updated paths and this dep is outdated, skip it
            if only_updated and not is_up_to_date:
                continue

            # If we reached the target, we found a path
            if dep.name == target:
                return True

            # Recursively check if we can reach target from this dependency
            if has_path_through_deps(
                dep.name, target, original_start, visited.copy(), only_updated
            ):
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

            if keep_outdated:
                # Old behavior: Only check up-to-date dependencies for redundancy
                if is_latest:
                    # Check if there's an alternative path through other up-to-date dependencies
                    if has_path_through_deps(module, dep.name, module, set(), only_updated=True):
                        redundant_deps.add((module, dep.name))
            else:
                # New behavior: Check all dependencies for redundancy (regardless of version)
                # Check if there's an alternative path through any dependencies
                if has_path_through_deps(module, dep.name, module, set(), only_updated=False):
                    redundant_deps.add((module, dep.name))

    return redundant_deps


def check_git_status(
    module_name: str, module_version: str, base_dir: Path
) -> str:
    """
    Check a module's git repository status.

    Returns one of four states:
    - DIRTY: repo has uncommitted changes or is ahead of remote branch
    - UPDATED: synced with remote, but HEAD is newer than the latest tag
    - UNPUBLISHED: synced with remote, HEAD matches a tag, but tag doesn't match current module version
    - CLEAN: synced with remote, HEAD matches a tag, and tag matches current module version

    Returns the status as a string.
    """
    try:
        # Use the provided base directory to find modules
        current_dir = base_dir
        module_dir = current_dir / module_name

        if not module_dir.exists() or not (module_dir / ".git").exists():
            # If module directory or .git doesn't exist, assume clean
            return "CLEAN"

        # Initialize GitPython repo
        repo = git.Repo(module_dir)

        # Check 1: Uncommitted changes (working directory dirty)
        if repo.is_dirty(untracked_files=True):
            return "DIRTY"  # Has uncommitted changes

        # Check 2: Check if ahead of remote branch
        try:
            current_branch = repo.active_branch
            tracking_branch = current_branch.tracking_branch()
            
            if tracking_branch:
                # Check if we're ahead of the remote
                commits_ahead = list(repo.iter_commits(f'{tracking_branch}..{current_branch}'))
                if len(commits_ahead) > 0:
                    return "DIRTY"  # Ahead of remote
        except Exception:
            # If we can't determine remote status, continue with tag checking
            pass

        # At this point, we know the repository is synced with remote (not DIRTY)
        # Now check the relationship between HEAD and tags

        # Get the commit hash of the current HEAD
        try:
            head_commit = repo.head.commit.hexsha
        except Exception:
            return "CLEAN"  # Can't determine HEAD, assume clean

        # Get the latest tag
        try:
            # Get all tags sorted by creation date
            tags = sorted(repo.tags, key=lambda t: t.commit.committed_date, reverse=True)
            if not tags:
                # No tags at all, assume UPDATED (commits exist but no tags)
                return "UPDATED"
            
            latest_tag = tags[0]
            latest_tag_commit = latest_tag.commit.hexsha
        except Exception:
            # No tags or error getting tags, assume UPDATED
            return "UPDATED"

        # Check if HEAD is newer than the latest tag
        if head_commit != latest_tag_commit:
            # Check if there are commits since the latest tag
            try:
                commits_since_tag = list(repo.iter_commits(f'{latest_tag}..HEAD'))
                if len(commits_since_tag) > 0:
                    return "UPDATED"  # HEAD is newer than latest tag
                else:
                    # This shouldn't happen (HEAD != tag but no commits between), but handle gracefully
                    return "UPDATED"
            except Exception:
                return "UPDATED"

        # At this point, HEAD matches the latest tag
        # Check if this tag matches the current module version
        version_tag = module_version  # Use semver format (x.y.z)
        
        if str(latest_tag) == version_tag:
            return "CLEAN"  # Tag matches current version
        else:
            return "UNPUBLISHED"  # Tag exists but doesn't match current version

    except Exception as e:
        # If any error occurs, assume clean (don't want git issues to break the graph)
        print(f"Warning: Could not check git status for {module_name}: {e}")
        return "CLEAN"


def get_all_git_statuses(
    newest_versions: Dict[str, Version],
    untracked_modules: Dict[str, Version],
    base_dir: Path,
) -> Dict[str, str]:
    """
    Check git status for all modules (registry and untracked).

    Returns a dictionary mapping module names to their git status:
    'CLEAN', 'UPDATED', 'DIRTY', or 'UNPUBLISHED'.
    """
    git_statuses = {}

    print("Checking git status for modules...")

    # Check registry modules
    for module_name, version in newest_versions.items():
        status = check_git_status(module_name, str(version), base_dir)
        git_statuses[module_name] = status
        if status != "CLEAN":
            print(f"  {module_name}: {status}")
        else:
            print(f"  {module_name}: clean")

    # Check untracked modules
    for module_name, version in untracked_modules.items():
        status = check_git_status(module_name, str(version), base_dir)
        git_statuses[module_name] = status
        if status != "CLEAN":
            print(f"  {module_name} (untracked): {status}")
        else:
            print(f"  {module_name} (untracked): clean")

    return git_statuses


def generate_dot_file(
    output_path: Path,
    newest_versions: Dict[str, Version],
    all_dependencies: Dict[str, List[Dependency]],
    git_statuses: Dict[str, str],
    untracked_modules: Dict[str, Version],
    show_outdated: bool = False,
) -> bool:
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
        redundant_deps = find_redundant_dependencies(
            all_dependencies, all_modules, keep_outdated=show_outdated
        )
        
        # Find modules with outdated dependencies (for red outline when not showing outdated)
        modules_with_outdated = find_modules_with_outdated_deps(
            all_dependencies, all_modules
        ) if not show_outdated else set()

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("digraph dependencies {\n")
            f.write("    rankdir=TB;\n")
            f.write("    node [shape=box, style=filled];\n")
            f.write("    edge [fontsize=10];\n\n")

            # Write nodes (modules)
            f.write("    // Modules\n")
            for module_name in sorted(all_modules.keys()):
                version = all_modules[module_name]
                label = f"{module_name}\\n{version}"

                # Choose node color based on git status and type
                git_status = git_statuses.get(module_name, "CLEAN")
                is_untracked = module_name in untracked_modules

                if is_untracked:
                    if git_status == "DIRTY":
                        color = "plum"  # Pinkish-purple for dirty untracked modules
                    elif git_status == "UPDATED":
                        color = "khaki"  # Same as old dirty color for updated untracked
                    elif git_status == "UNPUBLISHED":
                        color = "lightblue"  # Blue-ish for unpublished untracked
                    else:  # CLEAN
                        color = "mistyrose"  # Light pink for clean untracked modules
                else:
                    if git_status == "DIRTY":
                        color = "plum"  # Pink-ish for dirty registry modules  
                    elif git_status == "UPDATED":
                        color = "khaki"  # Same as old dirty color for updated modules
                    elif git_status == "UNPUBLISHED":
                        color = "lightblue"  # Blue-ish for unpublished modules
                    else:  # CLEAN
                        color = (
                            "#b1dbab"  # Custom light green for clean registry modules
                        )

                # Determine outline color (red if module has outdated dependencies)
                outline_color = "red" if module_name in modules_with_outdated else "black"
                
                f.write(
                    f'    "{module_name}" [label="{label}", fillcolor="{color}", '
                    f'color="{outline_color}"];\n'
                )

            f.write("\n    // Dependencies\n")

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

                    if show_outdated:
                        # Old behavior: Include edge if not redundant OR outdated
                        if not is_redundant or not is_latest:
                            if is_latest:
                                # Up-to-date dependency
                                f.write(f'    "{module_name}" -> "{dep.name}";\n')
                            else:
                                # Outdated dependency - use red color
                                latest_version = all_modules[dep.name]
                                label = f"{dep.version}\\n(latest: {latest_version})"
                                f.write(
                                    f'    "{module_name}" -> "{dep.name}" [color=red, fontcolor=red, label="{label}"];\n'
                                )
                    else:
                        # New behavior: Only include if not redundant (regardless of version)
                        if not is_redundant:
                            if is_latest:
                                # Up-to-date dependency
                                f.write(f'    "{module_name}" -> "{dep.name}";\n')
                            else:
                                # Outdated dependency - use red color
                                latest_version = all_modules[dep.name]
                                label = f"{dep.version}\\n(latest: {latest_version})"
                                f.write(
                                    f'    "{module_name}" -> "{dep.name}" [color=red, fontcolor=red, label="{label}"];\n'
                                )

            f.write("}\n")

        # Generate SVG file using dot command
        svg_path = output_path.with_suffix(".svg")
        try:
            result = subprocess.run(
                ["dot", "-Tsvg", str(output_path), "-o", str(svg_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                print(f"✓ Generated SVG file: {svg_path}")
            else:
                print(
                    f"Warning: Failed to generate SVG file. dot command error: {result.stderr}"
                )
        except FileNotFoundError:
            print(
                f"Warning: 'dot' command not found. Please install Graphviz to generate SVG files."
            )
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
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="Generate a dependency graph for roo modules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script creates a DOT file showing module dependencies with:
- Modules as nodes (name and newest version)
- Dependencies as directed edges
- Outdated dependencies in red
- Transitive dependencies removed (unless --show_outdated is specified)

By default, redundant dependencies are removed regardless of version,
and modules with outdated dependencies have red outlines.

With --show_outdated, redundant dependencies that are outdated are kept,
and modules use normal black outlines.
        """
    )
    parser.add_argument(
        '--show_outdated',
        action='store_true',
        help='Keep redundant links that reference outdated dependencies (old behavior)'
    )
    
    args = parser.parse_args()

    # Display configuration
    print("Configuration:")
    if IGNORED_MODULES:
        print(f"  Ignoring modules: {', '.join(IGNORED_MODULES)}")
    else:
        print("  No modules configured to be ignored")
    print(f"  Show outdated mode: {'enabled' if args.show_outdated else 'disabled'}")
    print()

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

    # Check git status for all modules (registry + untracked)
    git_statuses = get_all_git_statuses(
        newest_versions, untracked_modules, registry_dir.parent
    )

    # Calculate counts
    total_modules = len(newest_versions) + len(untracked_modules)
    clean_count = sum(1 for status in git_statuses.values() if status == "CLEAN")
    updated_count = sum(1 for status in git_statuses.values() if status == "UPDATED")
    dirty_count = sum(1 for status in git_statuses.values() if status == "DIRTY")
    unpublished_count = sum(1 for status in git_statuses.values() if status == "UNPUBLISHED")

    print(f"\nFound {len(newest_versions)} registry modules:")
    for module_name in sorted(newest_versions.keys()):
        version = newest_versions[module_name]
        dep_count = len(
            [
                dep
                for dep in all_dependencies.get(module_name, [])
                if dep.name in newest_versions or dep.name in untracked_modules
            ]
        )
        git_status = git_statuses.get(module_name, "CLEAN")
        status = git_status.lower() if git_status != "CLEAN" else "clean"
        print(f"  {module_name} v{version} ({dep_count} roo dependencies) - {status}")

    if untracked_modules:
        print(f"\nFound {len(untracked_modules)} untracked modules:")
        for module_name in sorted(untracked_modules.keys()):
            version = untracked_modules[module_name]
            git_status = git_statuses.get(module_name, "CLEAN")
            status = git_status.lower() if git_status != "CLEAN" else "clean"
            print(f"  {module_name} v{version} (untracked) - {status}")

    print(
        f"\nSummary: {clean_count} clean, {updated_count} updated, {unpublished_count} unpublished, {dirty_count} dirty modules"
    )

    # Generate DOT file
    if generate_dot_file(
        output_path,
        newest_versions,
        all_dependencies,
        git_statuses,
        untracked_modules,
        show_outdated=args.show_outdated,
    ):
        print(f"\n✓ Successfully generated dependency graph: {output_path}")

        # Check if SVG was generated
        svg_path = output_path.with_suffix(".svg")
        if svg_path.exists():
            print(f"✓ Also generated SVG visualization: {svg_path}")

        print(f"\nNode colors:")
        print(
            f"  Light green (#b1dbab): Clean registry modules (git status matches latest tag)"
        )
        print(
            f"  Khaki: Updated modules (commits since last tag)"
        )
        print(
            f"  Light blue: Unpublished modules (latest commit doesn't match current version tag)"
        )
        print(
            f"  Plum: Dirty modules (uncommitted changes or ahead of remote)"
        )
        print(f"  Misty rose: Clean untracked modules")
        if not args.show_outdated:
            print(f"  Red outline: Modules with outdated dependencies")
        print(f"  Red edges: Outdated dependencies")
        return True
    else:
        print(f"\n✗ Failed to generate dependency graph")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
