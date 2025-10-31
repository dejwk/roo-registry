#!/usr/bin/env python3
"""
Script to update library.json and library.properties files for a given module
based on its MODULE.bazel file.

Usage: python3 roo-registry/bin/update_library.py <module_name>

This script determines the base directory automatically based on its location
and looks for module directories as siblings to roo-registry.
The script will update existing library.json and library.properties files,
preserving their existing content and only updating version information.
"""

import sys
import json
import argparse
import re
from pathlib import Path
from typing import Dict, List, Optional

# Add the bin directory to the path to import module_utils
sys.path.insert(0, str(Path(__file__).parent))
from module_utils import parse_module_bazel, Dependency


def update_library_json(library_json_path: Path, module_version: str, dependencies: List[Dependency]) -> bool:
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
        roo_dependencies = [dep for dep in dependencies if dep.name.startswith('roo_') and dep.name != 'roo_testing']
        
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


def update_library_properties(library_properties_path: Path, module_version: str, dependencies: List[Dependency]) -> bool:
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
        roo_dependencies = [dep for dep in dependencies if dep.name.startswith('roo_') and dep.name != 'roo_testing']
        
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


def update_library_files(module_name: str, force: bool = False) -> bool:
    """
    Update library.json and library.properties for the given module.
    
    Returns True if successful, False otherwise.
    """
    # Determine the base directory from the script's location
    # Script is in roo-registry/bin/, so we need to go up two levels to get the parent of roo-registry
    script_path = Path(__file__).resolve()
    base_dir = script_path.parent.parent.parent  # bin -> roo-registry -> parent
    module_dir = base_dir / module_name
    
    print(f"Script location: {script_path}")
    print(f"Base directory: {base_dir}")
    
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
    parsed_name, parsed_version, dependencies = parse_module_bazel(module_bazel_path)
    
    if not parsed_name or not parsed_version:
        print(f"Error: Could not parse module name and version from MODULE.bazel")
        return False
    
    print(f"Parsed module: {parsed_name} v{parsed_version}")
    print(f"Dependencies: {len(dependencies)}")
    for dep in dependencies:
        print(f"  - {dep}")
    
    # Verify the parsed name matches the expected module name
    if parsed_name != module_name:
        print(f"Warning: Parsed module name '{parsed_name}' differs from expected '{module_name}'")
        if not force:
            print("Use --force to proceed anyway.")
            return False
    
    # Update library files
    library_json_path = module_dir / "library.json"
    library_properties_path = module_dir / "library.properties"
    
    success = True
    
    # Update library.json
    if not update_library_json(library_json_path, parsed_version, dependencies):
        success = False
    
    # Update library.properties
    if not update_library_properties(library_properties_path, parsed_version, dependencies):
        success = False
    
    return success


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Update library.json and library.properties for a roo module",
        epilog="Example: python3 roo-registry/bin/update_library.py roo_display"
    )
    parser.add_argument(
        "module_name",
        help="Name of the module to update (e.g., roo_display)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force update even if module name in MODULE.bazel differs"
    )
    
    args = parser.parse_args()
    
    success = update_library_files(args.module_name, args.force)
    
    if success:
        print(f"\n✓ Successfully updated library files for {args.module_name}")
        sys.exit(0)
    else:
        print(f"\n✗ Failed to update library files for {args.module_name}")
        sys.exit(1)


if __name__ == "__main__":
    main()
