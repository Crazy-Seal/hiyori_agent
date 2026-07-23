import logging
from pathlib import Path

from app.agent.utils.infra.log import _ensure_tool_file_handler
from app.runtime import get_data_dir


def test_tool_file_handler_uses_disposable_test_data_dir() -> None:
    logger = logging.getLogger("tests.tool_log_isolation")

    _ensure_tool_file_handler(logger)
    file_handlers = [
        handler
        for handler in logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]

    try:
        assert len(file_handlers) == 1
        assert Path(file_handlers[0].baseFilename) == (
            get_data_dir() / "logs" / "tools.log"
        )
    finally:
        for handler in file_handlers:
            logger.removeHandler(handler)
            handler.close()
