# FlyPrint Edge Windows Zip Package

This package is intended for Windows machines that already have Python installed.

## Package Layout

- `app/`: application source, static assets, and Python dependencies manifest
- `scripts/`: bootstrap and launch scripts used by the batch entrypoints
- `logs/`: bootstrap and runtime logs
- `temp/`: package-local temporary files

## First Run

1. Extract the zip to a writable directory.
2. Open `app/config.example.json` and prepare your node configuration.
3. If `app/config.json` does not exist yet, copy `app/config.example.json` to `app/config.json` and fill in the real values.
4. Double-click `start-edge.cmd`, or run it in `cmd`.

On first launch the package will:

- detect a usable Python launcher from `py -3` or `python`
- create `app/.venv`
- install `app/requirements.txt`
- start the service from `app/main.py`

Subsequent launches reuse the local virtual environment.

## Debug Launch

Use `start-edge-debug.cmd` when you need extra logs.

That launcher sets:

- `FLYPRINT_LOG_LEVEL=DEBUG`
- `FLYPRINT_DEBUG_LOGGING=true`

Logs are written to:

- `logs/bootstrap.log`
- `logs/edge-service.log`
- `logs/edge-service.error.log`

## Rebuild The Release Zip

From the source repository root:

```powershell
python release/windows_zip/build_release.py
```

The output is written to `dist/windows-zip/`.
