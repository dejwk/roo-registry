#!/usr/bin/env python3
"""
Script to update library.json and library.properties files for a given module
based on its MODULE.bazel file.

Usage: python3 roo-registry/bin/update_library.py <module_name> [--nolatest_deps]

This script determines the base directory automatically based on its location
and looks for module directories as siblings to roo-registry.
The script will update existing library.json and library.properties files,
preserving their existing content and only updating version information.

By default, it also inspects the roo-registry/modules directory and updates Roo
dependencies to the latest registered versions. With --nolatest_deps, exact
MODULE.bazel dependency versions are preserved and validated instead.
"""

import sys
import json
import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import parse_module_bazel, Dependency, Version


def get_latest_versions_from_registry(registry_dir: Path) -> Dict[str, Version]:
    """
    Scan the registry/modules directory to find the latest version of each module.
    
    Returns a dictionary mapping module names to their latest Version.
    """
    latest_versions = {}
    modules_dir = registry_dir / "modules"
    
    if not modules_dir.exists():
        print(f"Warning: Registry modules directory not found: {modules_dir}")
        return latest_versions
    
    for module_path in modules_dir.iterdir():
        if not module_path.is_dir() or not module_path.name.startswith("roo_"):
            continue
        
        module_name = module_path.name
        versions = []
        
        # Scan for version directories
        for version_path in module_path.iterdir():
            if version_path.is_dir():
                try:
                    version = Version(version_path.name)
                    if not (
                        (version_path / "MODULE.bazel").is_file()
                        and (version_path / "source.json").is_file()
                    ):
                        continue
                    versions.append(version)
                except ValueError:
                    # Skip invalid version directories
                    continue
        
        if versions:
            latest_versions[module_name] = max(versions)
    
    return latest_versions


def registry_version_exists(
    registry_dir: Path,
    dependency: Dependency,
) -> bool:
    """Return whether a complete Roo registry entry exists for a dependency."""
    version_dir = (
        registry_dir
        / "modules"
        / dependency.name
        / str(dependency.version)
    )
    return (
        version_dir.is_dir()
        and (version_dir / "MODULE.bazel").is_file()
        and (version_dir / "source.json").is_file()
    )


def get_missing_registry_dependencies(
    dependencies: List[Dependency],
    registry_dir: Path,
) -> List[Dependency]:
    """Return exact Roo dependency versions absent from the local registry."""
    return [
        dependency
        for dependency in dependencies
        if dependency.name.startswith("roo_")
        and not registry_version_exists(registry_dir, dependency)
    ]


def validate_registry_dependencies(
    dependencies: List[Dependency],
    registry_dir: Path,
) -> bool:
    """Validate that all exact Roo dependency versions are registered."""
    missing = get_missing_registry_dependencies(dependencies, registry_dir)
    if not missing:
        print("All exact Roo dependency versions exist in the registry")
        return True

    print("Error: Roo dependencies are missing from the local registry:")
    for dependency in missing:
        expected = (
            registry_dir
            / "modules"
            / dependency.name
            / str(dependency.version)
        )
        print(f"  {dependency} (expected {expected})")
    print("Register the missing dependency releases before preparing this module.")
    return False


def update_dependencies_to_latest(
    dependencies: List[Dependency],
    latest_versions: Dict[str, Version]
) -> Tuple[List[Dependency], List[str]]:
    """
    Update dependencies to use the latest versions from the registry.
    
    Returns a tuple of (updated_dependencies, update_messages).
    """
    updated_dependencies = []
    update_messages = []
    
    for dep in dependencies:
        if dep.name in latest_versions:
            latest = latest_versions[dep.name]
            if dep.version != latest:
                update_messages.append(
                    f"  {dep.name}: {dep.version} -> {latest}"
                )
                updated_dependencies.append(Dependency(dep.name, str(latest)))
            else:
                updated_dependencies.append(dep)
        else:
            # Dependency not in registry, keep as-is
            updated_dependencies.append(dep)
    
    return updated_dependencies, update_messages


def update_module_bazel(
    module_bazel_path: Path,
    updated_dependencies: List[Dependency]
) -> bool:
    """
    Update MODULE.bazel file with new dependency versions.
    """
    try:
        with open(module_bazel_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Create a mapping of dependency names to their new versions
        dep_map = {dep.name: str(dep.version) for dep in updated_dependencies}
        
        # Replace only the version string so multiline formatting, argument
        # order, comments, and trailing commas remain intact.
        call_pattern = re.compile(r'\bbazel_dep\s*\((.*?)\)', re.DOTALL)
        name_pattern = re.compile(r'\bname\s*=\s*(["\'])([^"\']+)\1')
        version_pattern = re.compile(r'\bversion\s*=\s*(["\'])([^"\']+)\1')

        def replace_version(match):
            body = match.group(1)
            name_match = name_pattern.search(body)
            version_match = version_pattern.search(body)
            if not name_match or not version_match:
                return match.group(0)

            dep_name = name_match.group(2)
            new_version = dep_map.get(dep_name)
            if not new_version or new_version == version_match.group(2):
                return match.group(0)

            value_start = (
                match.start(1) - match.start(0) + version_match.start(2)
            )
            value_end = (
                match.start(1) - match.start(0) + version_match.end(2)
            )
            call = match.group(0)
            return call[:value_start] + new_version + call[value_end:]

        updated_content = call_pattern.sub(replace_version, content)
        
        # Write back if changed
        if updated_content != content:
            with open(module_bazel_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            print(f"✓ Updated MODULE.bazel with new dependency versions")
            return True
        else:
            print("  MODULE.bazel already has latest dependency versions")
            return True
        
    except Exception as e:
        print(f"Error updating MODULE.bazel: {e}")
        return False


def update_library_json(
    library_json_path: Path,
    module_version: str,
    dependencies: List[Dependency],
    skip_dev_dependencies: bool = False,
) -> bool:
    """
    Update library.json file with new version and dependency information.
    Preserves all existing content except version and dependencies.
    """
    if not library_json_path.exists():
        print(f"Warning: {library_json_path} does not exist. Skipping library.json update.")
        return True
    
    try:
        # Read existing library.json
        with open(library_json_path, 'r', encoding='utf-8') as f:
            library_data = json.load(f)
        
        print(f"Current library.json version: {library_data.get('version', 'unknown')}")
        
        # Update version
        library_data['version'] = module_version
        
        # Filter to only roo dependencies (exclude external ones like nanopb and roo_testing)
        roo_dependencies = [
            dep for dep in dependencies
            if dep.name.startswith('roo_')
            and dep.name != 'roo_testing'
            and (not skip_dev_dependencies or not dep.dev_dependency)
        ]
        
        # Update dependencies in the existing format: "dejwk/<library_name>": ">=x.y.z"
        if roo_dependencies:
            library_data['dependencies'] = {}
            for dep in roo_dependencies:
                library_data['dependencies'][f"dejwk/{dep.name}"] = f">={dep.version}"
            print(f"Updated {len(roo_dependencies)} dependencies in library.json")
        else:
            # Remove dependencies section if no roo dependencies
            if 'dependencies' in library_data:
                del library_data['dependencies']
            print("No roo dependencies found, removed dependencies section")
        
        # Write updated library.json
        with open(library_json_path, 'w', encoding='utf-8') as f:
            json.dump(library_data, f, indent=4)
        
        print(f"✓ Updated library.json version to {module_version}")
        return True
        
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {library_json_path}: {e}")
        return False
    except Exception as e:
        print(f"Error updating library.json: {e}")
        return False


def update_library_properties(
    library_properties_path: Path,
    module_version: str,
    dependencies: List[Dependency],
    skip_dev_dependencies: bool = False,
) -> bool:
    """
    Update library.properties file with new version and dependency information.
    Preserves all existing content except version and depends fields.
    """
    if not library_properties_path.exists():
        print(f"Warning: {library_properties_path} does not exist. Skipping library.properties update.")
        return True
    
    try:
        # Read existing library.properties
        with open(library_properties_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        lines = content.split('\n')
        updated_lines = []
        version_updated = False
        depends_updated = False
        
        # Process each line
        for line in lines:
            if line.startswith('version='):
                current_version = line.split('=', 1)[1] if '=' in line else 'unknown'
                print(f"Current library.properties version: {current_version}")
                updated_lines.append(f'version={module_version}')
                version_updated = True
                print(f"✓ Updated library.properties version to {module_version}")
            elif line.startswith('depends='):
                # Remove existing depends line - we'll add the new one later
                depends_updated = True
                continue
            else:
                updated_lines.append(line)
        
        # Filter to only roo dependencies
        roo_dependencies = [
            dep for dep in dependencies
            if dep.name.startswith('roo_')
            and dep.name != 'roo_testing'
            and (not skip_dev_dependencies or not dep.dev_dependency)
        ]
        
        # Add new depends line if we have dependencies
        if roo_dependencies:
            dep_names = [dep.name for dep in roo_dependencies]
            depends_line = f"depends={','.join(dep_names)}"
            
            # Insert depends line before the last empty line(s) if any
            while updated_lines and updated_lines[-1] == '':
                updated_lines.pop()
            
            updated_lines.append(depends_line)
            print(f"Updated {len(roo_dependencies)} dependencies in library.properties")
        else:
            print("No roo dependencies found, removed depends field")
        
        # Add version line if it wasn't found
        if not version_updated:
            # Insert version after name if possible, otherwise at the beginning
            insert_pos = 0
            for i, line in enumerate(updated_lines):
                if line.startswith('name='):
                    insert_pos = i + 1
                    break
            updated_lines.insert(insert_pos, f'version={module_version}')
            print(f"✓ Added version={module_version} to library.properties")
        
        # Write updated library.properties
        updated_content = '\n'.join(updated_lines)
        if not updated_content.endswith('\n'):
            updated_content += '\n'
        
        with open(library_properties_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        return True
        
    except Exception as e:
        print(f"Error updating library.properties: {e}")
        return False


def update_library_files(
    module_name: str,
    force: bool = False,
    latest_deps: bool = True,
    skip_dev_dependencies: bool = False,
    *,
    registry_dir: Optional[Path] = None,
    base_dir: Optional[Path] = None,
) -> bool:
    """
    Update library.json and library.properties for the given module.
    
    Returns True if successful, False otherwise.
    """
    # Determine the base directory from the script's location
    # Script is in roo-registry/bin/, so we need to go up two levels to get the parent of roo-registry
    script_path = Path(__file__).resolve()
    if registry_dir is None:
        registry_dir = script_path.parent.parent  # bin -> roo-registry
    if base_dir is None:
        base_dir = registry_dir.parent  # roo-registry -> parent
    module_dir = base_dir / module_name
    
    print(f"Script location: {script_path}")
    print(f"Base directory: {base_dir}")
    print(f"Registry directory: {registry_dir}")
    
    if not module_dir.exists():
        print(f"Error: Module directory '{module_dir}' does not exist.")
        print(f"Base directory: {base_dir}")
        print(f"Expected module directory: {module_dir}")
        return False
    
    if not module_dir.is_dir():
        print(f"Error: '{module_dir}' is not a directory.")
        return False
    
    # Look for MODULE.bazel in the module directory
    module_bazel_path = module_dir / "MODULE.bazel"
    
    if not module_bazel_path.exists():
        print(f"Error: MODULE.bazel not found in '{module_dir}'.")
        return False
    
    print(f"Processing module: {module_name}")
    print(f"Module directory: {module_dir}")
    print(f"MODULE.bazel path: {module_bazel_path}")
    
    # Parse MODULE.bazel
    try:
        parsed_name, parsed_version, dependencies = parse_module_bazel(
            module_bazel_path
        )
    except ValueError as error:
        print(f"Error: {error}")
        return False
    
    if not parsed_name or not parsed_version:
        print(f"Error: Could not parse module name and version from MODULE.bazel")
        return False
    
    print(f"\nParsed module: {parsed_name} v{parsed_version}")
    print(f"Dependencies: {len(dependencies)}")
    for dep in dependencies:
        print(f"  - {dep}")
    
    # Verify the parsed name matches the expected module name
    if parsed_name != module_name:
        print(f"Warning: Parsed module name '{parsed_name}' differs from expected '{module_name}'")
        if not force:
            print("Use --force to proceed anyway.")
            return False
    
    if latest_deps:
        print("\nScanning registry for latest dependency versions...")
        latest_versions = get_latest_versions_from_registry(registry_dir)
        print(f"Found {len(latest_versions)} modules in registry")

        print("\nChecking for dependency updates...")
        updated_dependencies, update_messages = update_dependencies_to_latest(
            dependencies, latest_versions
        )

        if update_messages:
            print("Dependency updates found:")
            for msg in update_messages:
                print(msg)
        else:
            print("All dependencies are already at the latest registered version")

        if update_messages:
            print("\nUpdating MODULE.bazel...")
            if not update_module_bazel(module_bazel_path, updated_dependencies):
                return False
    else:
        print("\nPreserving dependency versions from MODULE.bazel...")
        if not validate_registry_dependencies(dependencies, registry_dir):
            return False
        updated_dependencies = dependencies
    
    # Update library files
    library_json_path = module_dir / "library.json"
    library_properties_path = module_dir / "library.properties"
    
    success = True
    
    # Update library.json
    print("\nUpdating library.json...")
    if not update_library_json(
        library_json_path,
        parsed_version,
        updated_dependencies,
        skip_dev_dependencies,
    ):
        success = False
    
    # Update library.properties
    print("\nUpdating library.properties...")
    if not update_library_properties(
        library_properties_path,
        parsed_version,
        updated_dependencies,
        skip_dev_dependencies,
    ):
        success = False
    
    return success


def create_argument_parser() -> argparse.ArgumentParser:
    """Create the command-line parser for update_library.py."""
    parser = argparse.ArgumentParser(
        description="Update library.json and library.properties for a roo module",
        epilog=(
            "Example: python3 roo-registry/bin/update_library.py roo_display "
            "--nolatest_deps"
        ),
    )
    parser.add_argument(
        "module_name",
        help="Name of the module to update (e.g., roo_display)"
    )
    parser.add_argument(
        "--skip-dev-dependencies",
        action="store_true",
        help="Exclude Bazel development dependencies from Arduino and PlatformIO metadata",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force update even if module name in MODULE.bazel differs"
    )
    parser.add_argument(
        "--nolatest_deps",
        "--no-latest-deps",
        action="store_true",
        help=(
            "Preserve exact MODULE.bazel dependency versions, verify their "
            "Roo registry entries, and only synchronize library metadata"
        ),
    )
    return parser


def main():
    """Main function."""
    args = create_argument_parser().parse_args()
    
    success = update_library_files(
        args.module_name,
        args.force,
        latest_deps=not args.nolatest_deps,
        skip_dev_dependencies=args.skip_dev_dependencies,
    )
    
    if success:
        print(f"\n✓ Successfully updated library files for {args.module_name}")
        sys.exit(0)
    else:
        print(f"\n✗ Failed to update library files for {args.module_name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
