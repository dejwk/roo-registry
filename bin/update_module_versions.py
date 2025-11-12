#!/usr/bin/env python3
"""
Script to update all roo module version references across modules.

This script:
1. Enumerates all roo modules (directories with MODULE.bazel files) in the roo directory
2. Identifies the current version of each module from its MODULE.bazel file
3. Updates all references to each module in other modules' MODULE.bazel and library.json files

Usage:
    python update_module_versions.py [--help] [--dry-run]
    
Options:
    --help      Show this help message
    --dry-run   Show what would be updated without making changes
"""

import os
import re
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional


def get_roo_directory() -> Path:
    """Get the roo directory path (two levels up from this script)."""
    script_dir = Path(__file__).parent.absolute()
    roo_dir = script_dir.parent.parent
    return roo_dir


def find_roo_modules(roo_dir: Path) -> List[Path]:
    """Find all roo module directories (those containing MODULE.bazel)."""
    modules = []
    
    for item in roo_dir.iterdir():
        if item.is_dir() and not item.name.startswith('.'):
            module_bazel = item / "MODULE.bazel"
            if module_bazel.exists():
                modules.append(item)
    
    return modules


def extract_module_version(module_dir: Path) -> Optional[Tuple[str, str]]:
    """Extract module name and version from MODULE.bazel file."""
    module_bazel = module_dir / "MODULE.bazel"
    
    if not module_bazel.exists():
        return None
    
    try:
        content = module_bazel.read_text()
        # Look for: module(name = "module_name", version = "x.y.z")
        match = re.search(r'module\s*\(\s*name\s*=\s*"([^"]+)"\s*,\s*version\s*=\s*"([^"]+)"\s*\)', content)
        if match:
            return match.group(1), match.group(2)
    except Exception as e:
        print(f"Error reading {module_bazel}: {e}")
    
    return None


def get_module_versions(roo_dir: Path) -> Dict[str, str]:
    """Get a mapping of module names to their current versions."""
    modules = find_roo_modules(roo_dir)
    versions = {}
    
    for module_dir in modules:
        version_info = extract_module_version(module_dir)
        if version_info:
            name, version = version_info
            versions[name] = version
            print(f"Found module {name} version {version}")
        else:
            print(f"Warning: Could not extract version from {module_dir}")
    
    return versions


def update_module_bazel(module_bazel_path: Path, module_versions: Dict[str, str], dry_run: bool = False) -> bool:
    """Update MODULE.bazel file with new module versions."""
    if not module_bazel_path.exists():
        return False
    
    try:
        content = module_bazel_path.read_text()
        original_content = content
        
        # Update bazel_dep lines: bazel_dep(name = "module_name", version = "x.y.z")
        for module_name, version in module_versions.items():
            pattern = rf'(bazel_dep\s*\(\s*name\s*=\s*"{re.escape(module_name)}"\s*,\s*version\s*=\s*")[^"]+(")'
            replacement = rf'\g<1>{version}\g<2>'
            content = re.sub(pattern, replacement, content)
        
        if content != original_content:
            if not dry_run:
                module_bazel_path.write_text(content)
            return True
        
    except Exception as e:
        print(f"Error updating {module_bazel_path}: {e}")
    
    return False


def update_library_json(library_json_path: Path, module_versions: Dict[str, str], dry_run: bool = False) -> bool:
    """Update library.json file with new module versions."""
    if not library_json_path.exists():
        return False
    
    try:
        with open(library_json_path, 'r') as f:
            data = json.load(f)
        
        if 'dependencies' not in data:
            return False
        
        updated = False
        dependencies = data['dependencies']
        
        for module_name, version in module_versions.items():
            dep_key = f"dejwk/{module_name}"
            if dep_key in dependencies:
                new_value = f">={version}"
                if dependencies[dep_key] != new_value:
                    dependencies[dep_key] = new_value
                    updated = True
        
        if updated and not dry_run:
            with open(library_json_path, 'w') as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
            # Add newline at end if not present
            if not library_json_path.read_text().endswith('\n'):
                library_json_path.write_text(library_json_path.read_text() + '\n')
        
        return updated
    
    except Exception as e:
        print(f"Error updating {library_json_path}: {e}")
    
    return False


def update_all_modules(roo_dir: Path, module_versions: Dict[str, str], dry_run: bool = False):
    """Update all modules with the current versions."""
    modules = find_roo_modules(roo_dir)
    
    for module_dir in modules:
        module_name = extract_module_version(module_dir)
        if module_name:
            module_name = module_name[0]
            
            # Update MODULE.bazel
            module_bazel_path = module_dir / "MODULE.bazel"
            if update_module_bazel(module_bazel_path, module_versions, dry_run):
                action = "Would update" if dry_run else "Updated"
                print(f"{action} {module_name}/MODULE.bazel")
            
            # Update library.json
            library_json_path = module_dir / "library.json"
            if update_library_json(library_json_path, module_versions, dry_run):
                action = "Would update" if dry_run else "Updated"
                print(f"{action} {module_name}/library.json")


def main():
    """Main function to run the module version updater."""
    # Parse command line arguments
    dry_run = "--dry-run" in sys.argv
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        return 0
    
    print("Roo Module Version Updater")
    print("=" * 40)
    
    if dry_run:
        print("DRY RUN MODE - No changes will be made")
        print("=" * 40)
    
    # Get roo directory
    roo_dir = get_roo_directory()
    print(f"Roo directory: {roo_dir}")
    
    if not roo_dir.exists():
        print(f"Error: Roo directory {roo_dir} does not exist")
        return 1
    
    # Discover all modules and their versions
    print("\nDiscovering modules...")
    module_versions = get_module_versions(roo_dir)
    
    if not module_versions:
        print("No modules found!")
        return 1
    
    print(f"\nFound {len(module_versions)} modules:")
    for name, version in sorted(module_versions.items()):
        print(f"  {name}: {version}")
    
    # Update all modules
    update_action = "Checking for updates..." if dry_run else "Updating module references..."
    print(f"\n{update_action}")
    update_all_modules(roo_dir, module_versions, dry_run)
    
    print("\nDone!")
    return 0


if __name__ == "__main__":
    exit(main())