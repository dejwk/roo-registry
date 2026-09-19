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
- Ignores Bazel development dependencies
- Highlights outdated dependencies in red
- By default, removes redundant transitive dependencies
- Modules with outdated dependencies have red outlines

**Note:** Should be run from the parent directory of roo-registry.

### `release.py`
Runs the complete interactive release workflow in order: preparation, GitHub
release and CI, then registry/PlatformIO publication.

```bash
python3 roo-registry/bin/release.py roo_display --patch
python3 roo-registry/bin/release.py roo_display --current --nolatest_deps
```

Accepts all `pre_release.py` options plus `--skip-publish` for PlatformIO.
Before committing and pushing, it shows the staged summary and release notes,
offers either the staged diff against HEAD or the complete diff since the last
release (including staged changes) in tig, then asks for approval. The last
release is the highest version tag reachable from HEAD; unrelated branch tags
and non-version tags are ignored. If no release tag exists, that review stops
before approval. Both views use tig's pager mode.
Install `tig` to use that optional review; a failed review stops publication.
GitHub publication has its own confirmation, and the new release URL is printed
before waiting for CI. Only green CI reaches the final confirmation to update
and push the registry, regenerate its graph, and publish to PlatformIO.
Each stage reports its outcome. Failure, declined approval, or interruption
stops the workflow without rolling back completed steps. If post-release is
declined, the script prints the standalone command to finish it later.

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

### `github_release.py`
Creates the GitHub release for a prepared module and waits for its continuous
test workflow to finish successfully.

**Usage:**
```bash
python3 github_release.py <module_name>
```

**Purpose:**
- Reads the release version from the module's `MODULE.bazel`
- Reads the matching top entry of `RELEASE_NOTES.md` and displays the planned actions
- Adds a GitHub compare link for the full changelog when a previous tag exists
- Creates the GitHub release and its version tag at the module's current `HEAD`
- Waits for the tag-triggered `CI` GitHub Actions workflow to become green
- Offers to run `post_release.py` after CI succeeds

Requires an authenticated [GitHub CLI](https://cli.github.com/).


### `pre_release.py`
Prepares a module release, synchronizes dependency metadata, tests it, and
pushes the resulting commits.

**Usage:**
```bash
python3 pre_release.py <module_name> [--major|--minor|--patch|--current] \
    [--nolatest_deps] [--skip-tests] [--notes "Markdown release notes"]
```

**Example:**
```bash
python3 pre_release.py roo_display --patch
python3 pre_release.py roo_display
python3 pre_release.py roo_display --current
python3 pre_release.py roo_display --current --nolatest_deps
```

**Options:**
- `--major`: Increment major version (x.0.0)
- `--minor`: Increment minor version (0.x.0) 
- `--patch`: Increment patch version (0.0.x)
- `--current`: Prepare the version already declared in `MODULE.bazel` without
  incrementing it. A clean branch may be ahead of its upstream in this mode;
  those existing commits are tested and pushed with any metadata commit.
- With no version flag, an unpublished current version is reused. Otherwise,
  Codex recommends `major`, `minor`, or `patch` from the repository changes and
  proposed release notes. Breaking changes or major new functionality select
  `major`; significant new functionality selects `minor`; bug fixes and minor
  tweaks select `patch`.
- `--nolatest_deps` (alias `--no-latest-deps`): Preserve exact
  `MODULE.bazel` dependency versions, require every exact `roo_*` dependency
  version to have a complete registry entry, and synchronize `library.json`
  and `library.properties` from those pins.
- `--skip-tests`: Skip running bazel tests
- `--notes`: Markdown body for the release-note entry. If omitted and matching
  notes already exist, the script asks before replacing them. Otherwise, a
  read-only Codex invocation proposes the notes.
  Set `CODEX_BIN` to an executable Codex CLI path when it is not on `PATH`; the
  script also detects Codex installed by the VS Code extension.

After metadata synchronization and tests, the script prints the staged git
changes and release notes, then asks for confirmation before committing and
pushing.

If `HEAD` has the same tree as the newest reachable published version tag, the
script asks whether to proceed before generating notes or modifying any files.
Declining leaves the working tree, index, and commits unchanged.

Without `--nolatest_deps`, all four version modes select the maximum registered
version of each Roo dependency before synchronizing the manifests. Keep the
local registry current and publish dependencies first when releasing related
libraries.

**Purpose:**
- Verifies git status is clean and up-to-date
- Selects the current version or increments it in `MODULE.bazel`
- Selects the latest registered Roo dependencies by default, or validates and
  preserves exact pins with `--nolatest_deps`
- Updates library.json and library.properties
- Creates or updates the matching top `RELEASE_NOTES.md` entry
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
python3 update_library.py <module_name> [--nolatest_deps]
```

**Example:**
```bash
python3 update_library.py roo_display
python3 update_library.py roo_display --nolatest_deps
```

**Purpose:**
- Updates library metadata files
- Preserves existing content while updating version information
- Synchronizes dependency information from `MODULE.bazel`
- Updates dependencies to the latest available version from the local registry
  by default
- With `--nolatest_deps`, preserves exact dependency pins and fails before
  writing if an exact Roo dependency version is absent from the registry

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
- Release-script unit tests run with
  `python3 -m unittest discover -s tests -v`
