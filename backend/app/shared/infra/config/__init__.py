"""Public configuration entrypoint.

对外只暴露：
- `Settings`
- `get_settings()`
- `resolve_project_config_path()`
"""

from .settings import Settings, get_settings
from .support import resolve_project_config_path

__all__ = [
    "Settings",
    "get_settings",
    "resolve_project_config_path",
]
