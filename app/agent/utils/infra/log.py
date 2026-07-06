import datetime as dt
import functools
import inspect
import logging
import time
from pathlib import Path
from threading import Lock
from typing import Any


def shorten_for_log(text: str, max_len: int = 200) -> str:
    """限制日志长度，避免控制台被超长内容刷屏。"""
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}..."


_SENSITIVE_KEYS = {"api_key", "token", "password", "secret", "authorization"}
_TOOL_LOGGER_LOCK = Lock()
# 解析到 app/agent/tools/tools.log
_TOOL_LOG_FILE = Path(__file__).resolve().parents[2] / "tools" / "tools.log"


def _ensure_tool_file_handler(logger: logging.Logger) -> None:
    """为工具日志器附加文件输出，避免重复添加 handler。"""
    target = str(_TOOL_LOG_FILE.resolve())
    with _TOOL_LOGGER_LOCK:
        for handler in logger.handlers:
            if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == target:
                return

        _TOOL_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(_TOOL_LOG_FILE, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
        )
        logger.addHandler(file_handler)


def _sanitize_value(value: Any) -> Any:
    """将参数/输出转换为可读且安全的日志片段。"""
    if isinstance(value, str):
        return shorten_for_log(value, max_len=500)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if any(word in key_str.lower() for word in _SENSITIVE_KEYS):
                safe[key_str] = "***"
            else:
                safe[key_str] = _sanitize_value(item)
        return safe
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value[:20]]
    return shorten_for_log(repr(value), max_len=500)


def _sanitize_params(params: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in params.items():
        key_lower = key.lower()
        if any(word in key_lower for word in _SENSITIVE_KEYS):
            safe[key] = "***"
            continue
        safe[key] = _sanitize_value(value)
    return safe


async def log_tool_call_result(
    tool_name: str,
    params: dict[str, Any],
    result: Any,
    *,
    logger_name: str = "app.agent.tools",
) -> Any:
    """记录一次工具调用的参数和输出。

    适用于调用点已取得工具名、参数字典和结果的场景，写入前统一脱敏。

    返回原始 result，方便链式书写：return await log_tool_call_result(...)
    """
    logger = logging.getLogger(logger_name)
    _ensure_tool_file_handler(logger)
    call_time = dt.datetime.now(dt.UTC).isoformat()
    safe_params = _sanitize_params(dict(params or {}))
    result_preview = _sanitize_value(result)

    # 结果若为字符串且以 "错误:" 开头，按错误记录
    text_preview = result if isinstance(result, str) else getattr(result, "content", None)
    if isinstance(text_preview, str) and text_preview.lstrip().startswith("错误:"):
        logger.error(
            "tool=%s event=error call_time=%s params=%s error=%s",
            tool_name, call_time, safe_params, result_preview,
        )
    else:
        logger.info(
            "tool=%s event=success call_time=%s params=%s output=%s",
            tool_name, call_time, safe_params, result_preview,
        )
    return result


def log_tool_call(logger_name: str = "app.agent.tools"):
    """为普通同步或异步函数记录调用时间、参数、输出和异常。"""

    def decorator(func):
        signature = inspect.signature(func)

        def _prepare_log_context(args, kwargs):
            logger = logging.getLogger(logger_name)
            _ensure_tool_file_handler(logger)
            call_time = dt.datetime.now(dt.UTC).isoformat()
            start = time.perf_counter()
            try:
                bound = signature.bind_partial(*args, **kwargs)
                params = _sanitize_params(dict(bound.arguments))
            except Exception:
                params = {"args": _sanitize_value(args), "kwargs": _sanitize_value(kwargs)}
            logger.info("tool=%s event=start call_time=%s params=%s", func.__name__, call_time, params)
            return logger, call_time, start, params

        def _log_success_or_error(logger, call_time, start, params, result):
            duration_ms = int((time.perf_counter() - start) * 1000)
            result_preview = _sanitize_value(result)
            if isinstance(result, str) and result.lstrip().startswith("错误:"):
                logger.error(
                    "tool=%s event=error call_time=%s duration_ms=%s params=%s error=%s",
                    func.__name__,
                    call_time,
                    duration_ms,
                    params,
                    result_preview,
                )
            else:
                logger.info(
                    "tool=%s event=success call_time=%s duration_ms=%s params=%s output=%s",
                    func.__name__,
                    call_time,
                    duration_ms,
                    params,
                    result_preview,
                )

        def _log_exception(logger, call_time, start, params, exc: Exception):
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.exception(
                "tool=%s event=exception call_time=%s duration_ms=%s params=%s error=%s",
                func.__name__,
                call_time,
                duration_ms,
                params,
                shorten_for_log(str(exc), max_len=500),
            )

        if inspect.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                logger, call_time, start, params = _prepare_log_context(args, kwargs)
                try:
                    result = await func(*args, **kwargs)
                    _log_success_or_error(logger, call_time, start, params, result)
                    return result
                except Exception as exc:
                    _log_exception(logger, call_time, start, params, exc)
                    raise

            return async_wrapper

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger, call_time, start, params = _prepare_log_context(args, kwargs)
            try:
                result = func(*args, **kwargs)
                _log_success_or_error(logger, call_time, start, params, result)
                return result
            except Exception as exc:
                _log_exception(logger, call_time, start, params, exc)
                raise

        return wrapper

    return decorator
