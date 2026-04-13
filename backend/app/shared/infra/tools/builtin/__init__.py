"""内置工具注册入口。

应用启动时导入此包即可完成所有内置工具注册。后续在该目录新增工具模块后，
只需要在这里补一条 import 即可。
"""

from app.shared.infra.tools.builtin import content_analysis  # noqa: F401
from app.shared.infra.tools.builtin import memory_ops  # noqa: F401
from app.shared.infra.tools.builtin import search_kb  # noqa: F401
from app.shared.infra.tools.builtin import web_reading  # noqa: F401
from app.shared.infra.tools.builtin import web_search  # noqa: F401
