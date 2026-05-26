# Windows Green Package Bootstrap Design

**Date:** 2026-05-26

## Context

`fly-print-edge` is currently a Python-based edge print service with:

- A FastAPI backend started from `main.py`
- Static admin and user frontends under `static/`
- Windows-specific printing integrations through `pywin32` and `WMI`
- Project-local temp file handling through `portable_temp.py`

The current developer workflow assumes Python and dependencies are already present. That is good for local development, but it is not a good distribution story for Windows target machines.

The packaging goal for this iteration is not a frozen `exe`. The goal is a reusable, debuggable, low-friction Windows distribution that does not require the operator to manually install Python or understand Python dependency management.

## Goal

Ship a `win-x64` green package and matching zip release that:

- Keeps the release archive small
- Runs from an extracted directory without a system-wide install
- Preserves source code and logs for debugging
- Automatically prepares its own Python runtime and dependencies on first launch
- Reuses the prepared local environment on subsequent launches

## Non-Goals

- No MSI installer in this iteration
- No frozen `onefile` or `onedir` executable as the primary delivery artifact
- No Windows 32-bit support
- No Linux-specific packaging work beyond keeping source-based compatibility intact

## Constraints

- Target platform: Windows x64
- Target machine may initially have no Python installed
- Target machine can access the network to download runtime and dependencies
- Package size should stay as small as practical
- Debuggability is more important than hiding implementation details

## Approaches Considered

### 1. PyInstaller-based executable

This was rejected as the primary solution because it increases build time, makes debugging harder, complicates static resource handling, and works against the "fast dist" requirement.

### 2. Ship a full prebuilt runtime and `.venv`

This was rejected because it produces a larger package and makes the environment more brittle. A copied `.venv` is path-sensitive, difficult to refresh cleanly, and less trustworthy than rebuilding a local environment from a locked dependency set.

### 3. Bootstrap a local runtime on first launch

This is the recommended approach. The release archive stays small, the operator gets a green package, and the prepared runtime remains fully local to the extracted directory.

## Recommended Architecture

The release should be a self-bootstrapping green package.

The archive contains:

- Application source code
- Static resources
- Configuration template
- Startup scripts
- Dependency manifests
- Empty runtime/log/temp directories

The archive does not contain:

- A full Python interpreter
- A prebuilt virtual environment
- Installed third-party packages

At first launch, the package downloads a Windows x64 Python runtime into the local release directory, creates a local virtual environment for the app, installs locked dependencies, then starts the service. After that, launches become lightweight because the local runtime and environment are reused.

## Release Directory Layout

The release directory should follow this structure:

```text
flyprint-edge-win-x64/
  app/
    main.py
    *.py
    static/
    requirements.txt
    requirements.lock.txt
    config.example.json
    docs/
  runtime/
    python/
  logs/
  temp/
  scripts/
    bootstrap.ps1
    launch.ps1
    install-runtime.ps1
  start-edge.cmd
  start-edge-debug.cmd
  README-runtime.md
```

### Layout Notes

- `app/` contains the actual project source and static assets
- `runtime/python/` stores the downloaded local interpreter
- `logs/` stores bootstrap and launch diagnostics
- `temp/` is created up front to match the existing project-local temp model
- `scripts/` contains the operational logic instead of burying it in a single startup file
- `requirements.lock.txt` is the release installation source of truth

## Startup Model

### First Launch

1. The user runs `start-edge.cmd` or `start-edge-debug.cmd`
2. The wrapper calls `scripts/bootstrap.ps1`
3. `bootstrap.ps1` checks whether the local Python runtime exists
4. If missing, `install-runtime.ps1` downloads and prepares the runtime under `runtime/python/`
5. `bootstrap.ps1` checks whether `app/.venv` exists
6. If missing, it creates `app/.venv` with the local runtime
7. It installs dependencies from `app/requirements.lock.txt`
8. It hands control to `scripts/launch.ps1`
9. `launch.ps1` starts `app/main.py`

### Subsequent Launches

1. The wrapper calls `scripts/bootstrap.ps1`
2. Existing runtime and `.venv` are detected
3. Bootstrap skips setup
4. `launch.ps1` starts the service immediately

## Why We Do Not Ship `venv/`

Shipping a prebuilt virtual environment was rejected for four reasons:

1. It is not reliably portable across machines and directories
2. It tends to capture developer-machine state that should not be part of release output
3. Windows-specific packages such as `pywin32` and `WMI` are safer when installed into the local target environment
4. Rebuilding from a lock file is a cleaner upgrade path than trying to patch or overwrite an old copied environment

## Dependency Strategy

The project should keep two dependency files:

- `requirements.txt`
  - Human-maintained developer dependency list
- `requirements.lock.txt`
  - Release-grade locked dependency snapshot used on target machines

### Installation Rule

The bootstrap flow always installs from `requirements.lock.txt`, not from the looser developer file.

### Rationale

This keeps development readable while making target-machine bootstrap deterministic and easier to support.

## Script Responsibilities

The release should use four script layers.

### 1. User Entry Layer

- `start-edge.cmd`
- `start-edge-debug.cmd`

Responsibilities:

- Switch to the package root
- Invoke the PowerShell bootstrap entrypoint
- Pass normal or debug mode

These wrappers should stay intentionally thin.

### 2. Bootstrap Layer

- `scripts/bootstrap.ps1`

Responsibilities:

- Ensure required directories exist
- Check for local runtime presence
- Check for local `.venv` presence
- Create or refresh the environment when missing
- Hand off to the launch layer

This layer coordinates environment preparation but does not start application logic directly.

### 3. Runtime Installation Layer

- `scripts/install-runtime.ps1`

Responsibilities:

- Download the Windows x64 Python runtime to the package-local runtime directory
- Validate that the interpreter is usable
- Prepare `pip` if required by the selected runtime source

This layer must fail fast. A partial runtime install must not continue into application launch.

### 4. Application Launch Layer

- `scripts/launch.ps1`

Responsibilities:

- Start the service using the prepared local environment
- Set the working directory correctly
- Ensure `logs/` and `temp/` are present
- Emit concise startup diagnostics such as config presence and expected local URL

## Failure Handling

The bootstrap and launch experience should fail explicitly and locally.

Required behaviors:

- If the network is unavailable during first launch, explain that first-run setup requires internet access
- If runtime download fails, show which step failed instead of a generic startup error
- If dependency installation fails, point the operator to `logs/bootstrap.log`
- If `config.json` is missing, allow startup to continue but clearly explain that `config.example.json` must be copied and configured
- Persist bootstrap logs under `logs/` so errors are not lost when the console closes

## Distribution Workflow

The release workflow should be split into two simple scripts.

### `build-release.ps1`

Responsibilities:

- Assemble the green package directory
- Copy source, static files, config template, dependency manifests, and startup scripts
- Create required empty directories

This script should not perform heavyweight packaging or binary freezing.

### `pack-release.ps1`

Responsibilities:

- Compress the prepared release directory into `flyprint-edge-win-x64.zip`

This keeps "prepare release" and "archive release" separate, which makes iteration faster and easier to debug.

## Debugging Model

This design intentionally keeps debugging simple:

- Source code remains visible inside the release package
- Runtime and virtual environment remain local to the package
- Logs are written to package-local storage
- A debug launcher exposes more verbose setup and startup output

This is better suited to field diagnosis than a frozen executable.

## Linux Note

Linux packaging is out of scope for this design. The codebase should remain source-runnable on Linux, but no Linux-specific release artifact is required in this iteration.

## Implementation Summary

Implementation should produce:

- A package-local bootstrap runtime flow for Windows x64
- New startup scripts separated by responsibility
- A locked dependency install path
- A standard release directory assembler
- A zip packer for release distribution

The result is a small, reusable, debuggable Windows green package that bootstraps itself on first launch and becomes fast to relaunch afterward.
