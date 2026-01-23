# Roo Registry Bin Scripts

This directory contains utility scripts for managing the roo module registry and library dependencies.

## Scripts Overview

### `add.sh`
Adds a specific new library version to the Bazel registry, fetching it from GitHub. 
To be called after a library release.

**Usage:**
```bash
./add.sh <library_name> <library_version>
```

**Example:**
```bash
./add.sh roo_display 1.2.3
```

### `generate_dependency_graph.py`
Generates a visual dependency graph of all roo modules in DOT and SVG format.

**Usage:**
```bash
python3 generate_dependency_graph.py [--show_outdated]
```

**Options:**
- `--show_outdated`: Keep redundant links that reference outdated dependencies

**Purpose:** 
- Creates a `dependencies.dot` file in `roo-registry/doc/`
- Shows modules as nodes with their newest versions
- Shows dependencies as directed edges
- Highlights outdated dependencies in red
- By default, removes redundant transitive dependencies
- Modules with outdated dependencies have red outlines

**Note:** Should be run from the parent directory of roo-registry.

### `post_release.py`
Finalizes a module release by updating the registry and publishing.

**Usage:**
```bash
python3 post_release.py <module_name> [--skip-publish]
```

**Example:**
```bash
python3 post_release.py roo_display
```

**Options:**
- `--skip-publish`: Skip publishing to PlatformIO

**Purpose:**
- Cleans bazel artifacts and pulls latest changes
- Adds the new version to the registry using add.sh
- Updates the dependency graph
- Amends the commit to include dependency graph changes
- Pushes to remote
- Publishes to PlatformIO registry

### `pre_release.py`
Prepares a module for release by incrementing version and updating files.

**Usage:**
```bash
python3 pre_release.py <module_name> --major|--minor|--patch [--skip-tests]
```

**Example:**
```bash
python3 pre_release.py roo_display --patch
```

**Options:**
- `--major`: Increment major version (x.0.0)
- `--minor`: Increment minor version (0.x.0) 
- `--patch`: Increment patch version (0.0.x)
- `--skip-tests`: Skip running bazel tests

**Purpose:**
- Verifies git status is clean and up-to-date
- Increments the version number in MODULE.bazel
- Updates library.json and library.properties
- Runs bazel tests
- Commits and pushes the changes

### `update_deps.py`
Scans the modules directory to find all modules and their available versions.
Non-mutating.

**Usage:**
```bash
python3 update_deps.py
```

**Purpose:** 
- Discovers all modules in the `modules/` directory
- Identifies the newest version of each module
- Analyzes dependency relationships between modules

### `update_library.py`
Updates library.json and library.properties files for a specific module based on its MODULE.bazel file.

**Usage:**
```bash
python3 update_library.py <module_name>
```

**Example:**
```bash
python3 update_library.py roo_display
```

**Purpose:**
- Updates library metadata files
- Preserves existing content while updating version information
- Synchronizes dependency information from MODULE.bazel files
- Updates dependencies to the latest available version from the registry

### `update_module_versions.py`
Updates all roo module version references across all modules in the registry.

**Usage:**
```bash
python3 update_module_versions.py [--dry-run]
```

**Options:**
- `--dry-run`: Show what would be updated without making changes
- `--help`: Show help message

**Purpose:**
- Enumerates all roo modules with MODULE.bazel files
- Identifies current versions of each module
- Updates version references in MODULE.bazel and library.json files across all modules

### `sync.py`
Synchronizes the local state of all roo modules with GitHub repositories.

**Usage:**
```bash
python3 sync.py
```

**Purpose:**
- Pushes any non-pushed committed changes from roo-registry repository
- Pulls remote changes to roo-registry with rebase
- Discovers all tracked modules from roo-registry/modules directory
- For each module: pushes local changes and pulls remote changes with rebase
- Provides summary of uncommitted changes and sync failures

### `module_utils.py`
Shared utility library for working with roo modules and their dependencies.

**Purpose:** Provides common functionality used by other scripts including:
- Version parsing and comparison
- Dependency management
- Module.bazel file parsing

**Note:** This is a library module imported by other scripts, not meant to be run directly.

## General Notes

- Python scripts should be run from the parent directory of roo-registry
- Most scripts automatically detect the roo directory structure
- The `--dry-run` option is available in `update_module_versions.py` for safe testing
- Scripts work with the standard roo module structure using MODULE.bazel files
