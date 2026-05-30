# Copilot Instructions

- When a workspace includes libraries under `lib/`, check whether they are symlinks before scanning. Prefer the canonical source repository and avoid reading both the symlinked copy and the target.
- Ignore build-generated sources under `bazel-*` directories, including duplicated Roo library copies pulled in through Bazel externals.
- Ignore `.piodeps` library copies when a local repository exists. For Roo libraries, prefer local repositories under `~/Documents/Arduino/roo`.