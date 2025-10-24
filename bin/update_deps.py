
#!/usr/bin/env python3
"""
Script to determine all modules in the modules directory and find their newest versions.
Assumes modules are stored as:
modules/
  module1/
    1.0.0/
    1.0.1/
    1.1.0/
  module2/
    2.0.0/
    2.1.0/
"""

import os
import re
import sys
from typing import List, Tuple, Dict, Set
from pathlib import Path

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


def main():
    """Main function to scan modules and print newest versions."""
    # Get the script directory and assume modules directory is in the parent of the script directory
    # Script is at: some_dir/bin/update_deps.py
    # Modules is at: some_dir/modules/
    script_dir = Path(__file__).parent
    modules_dir = script_dir.parent / "modules"
    
    print(f"Scanning modules directory: {modules_dir}")
    
    # Get all modules and their versions
    modules = get_modules_and_versions(modules_dir)
    
    if not modules:
        print("No modules found or no valid versions detected.")
        return
    
    # Find newest versions
    newest_versions = find_newest_versions(modules)
    
    # Get dependencies for all newest versions
    all_dependencies = get_all_dependencies(modules_dir, newest_versions)
    
    # Print results
    print("\nModules and their newest versions:")
    print("-" * 60)
    
    # Track outdated dependencies for summary
    outdated_deps_summary = {}
    
    # Sort modules by name for consistent output
    for module_name in sorted(newest_versions.keys()):
        newest_version = newest_versions[module_name]
        total_versions = len(modules[module_name])
        dependencies = all_dependencies.get(module_name, [])
        
        print(f"{module_name:<25} {newest_version} ({total_versions} version{'s' if total_versions != 1 else ''} available)")
        
        if dependencies:
            print(f"{'':>25} Dependencies:")
            
            # Check which dependencies are outdated
            checked_dependencies = check_dependency_versions(dependencies, newest_versions)
            
            for dep, is_latest in checked_dependencies:
                if is_latest:
                    print(f"{'':>27} - {dep}")
                else:
                    # Highlight outdated dependency
                    latest_version = newest_versions[dep.name]
                    print(f"{'':>27} - {dep} *** OUTDATED (latest: {latest_version}) ***")
                    
                    # Track for summary
                    if dep.name not in outdated_deps_summary:
                        outdated_deps_summary[dep.name] = {
                            'used_versions': set(),
                            'latest_version': latest_version,
                            'used_by': []
                        }
                    outdated_deps_summary[dep.name]['used_versions'].add(str(dep.version))
                    outdated_deps_summary[dep.name]['used_by'].append(module_name)
        else:
            print(f"{'':>25} No dependencies")
        print()  # Empty line for readability
    
    print(f"Total modules found: {len(newest_versions)}")
    
    # Summary of all unique dependencies
    all_unique_deps = set()
    for deps in all_dependencies.values():
        for dep in deps:
            all_unique_deps.add(dep.name)
    
    if all_unique_deps:
        print(f"\nUnique dependencies across all modules:")
        for dep_name in sorted(all_unique_deps):
            print(f"  - {dep_name}")
        print(f"\nTotal unique dependencies: {len(all_unique_deps)}")
    
    # Summary of outdated dependencies
    if outdated_deps_summary:
        print(f"\n{'='*60}")
        print("OUTDATED DEPENDENCIES SUMMARY:")
        print(f"{'='*60}")
        
        for dep_name in sorted(outdated_deps_summary.keys()):
            info = outdated_deps_summary[dep_name]
            used_versions = sorted(info['used_versions'])
            latest_version = info['latest_version']
            used_by = sorted(info['used_by'])
            
            print(f"\n{dep_name}:")
            print(f"  Latest version: {latest_version}")
            print(f"  Used versions:  {', '.join(used_versions)}")
            print(f"  Used by:        {', '.join(used_by)}")
        
        print(f"\nTotal modules with outdated dependencies: {len(outdated_deps_summary)}")
    else:
        print(f"\n{'='*60}")
        print("✓ All dependencies are using the latest versions!")
        print(f"{'='*60}")


if __name__ == "__main__":
    main()