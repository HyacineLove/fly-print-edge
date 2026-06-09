import platform
import subprocess
from typing import Any, Dict


def hidden_subprocess_kwargs() -> Dict[str, Any]:
    if platform.system() != "Windows":
        return {}

    kwargs: Dict[str, Any] = {}
    startupinfo_factory = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_factory is not None:
        startupinfo = startupinfo_factory()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        if hasattr(startupinfo, "wShowWindow"):
            startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo

    kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return kwargs


def run_hidden(command, **kwargs):
    options = hidden_subprocess_kwargs()
    options.update(kwargs)
    return subprocess.run(command, **options)
