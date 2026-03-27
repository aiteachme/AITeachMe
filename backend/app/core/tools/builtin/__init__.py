"""内置工具注册入口。

应用启动时 import 此包即可注册所有内置工具。
后续在此目录下新增工具文件后，在此处 import 即可。
"""

from app.core.tools.builtin import memory_ops  # noqa: F401
from app.core.tools.builtin import search_kb  # noqa: F401
from app.core.tools.builtin import web_search  # noqa: F401


