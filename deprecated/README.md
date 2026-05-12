# Deprecated artifacts

This directory keeps old Kodi repository/static artifacts for rollback or diagnostics without advertising them in the active repository metadata.

- `root-static/` contains legacy root-level static repository files that were replaced by `repo_static/` as the source of truth.
- `repo-static/` contains old `repo_static/` packages removed from the active Kodi repository index, including historical `script.xbox.proxy` versions and diagnostic/dependency packages.

The active Kodi repository is `repo_static/` and currently advertises only the current `script.xbox.proxy` package.
