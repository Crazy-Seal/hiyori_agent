"""在导入应用模块前，强制所有后端测试使用一次性存储目录。"""

import os
import tempfile


_TEST_STORAGE = tempfile.TemporaryDirectory(prefix="ayaya-tests-")
os.environ["AYAYA_ENV"] = "test"
os.environ["AYAYA_DATA_DIR"] = _TEST_STORAGE.name
os.environ["AYAYA_API_TOKEN"] = "t" * 43

# 生产环境的路径覆盖值不得泄漏到测试进程中。
for variable in (
    "AYAYA_CHAT_SETTINGS_FILE",
    "AYAYA_MCP_SETTINGS_FILE",
    "MEMORY_BASE_PATH",
    "MEM0_QDRANT_PATH",
):
    os.environ.pop(variable, None)


def pytest_sessionfinish(session, exitstatus) -> None:
    _TEST_STORAGE.cleanup()
