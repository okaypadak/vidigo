import contextlib
import contextvars
import logging
import os
import queue
import threading
from collections import defaultdict, deque


_operation_id_var = contextvars.ContextVar("vidigo_operation_id", default="-")


def _stringify(value):
    text = str(value)
    return text.replace("\r", " ").replace("\n", " \\n ").strip()


def _format_variables(variables):
    parts = []
    for key, value in variables.items():
        if value is None:
            continue
        text = _stringify(value)
        if not text:
            continue
        parts.append(f"{key}={text}")
    return " | ".join(parts)


class OperationContextFilter(logging.Filter):
    def filter(self, record):
        if not getattr(record, "operation_id", None):
            record.operation_id = _operation_id_var.get() or "-"
        if not getattr(record, "stage", None):
            record.stage = "-"
        return True


class PlainTextFormatter(logging.Formatter):
    default_time_format = "%Y-%m-%d %H:%M:%S"

    def format(self, record):
        timestamp = self.formatTime(record, self.default_time_format)
        message = record.getMessage()
        return (
            f"{timestamp} | {record.levelname:<7} | {record.name} | "
            f"op={record.operation_id} | stage={record.stage} | {message}"
        )


class LogStreamHub:
    def __init__(self, backlog_limit=400):
        self._backlog_limit = backlog_limit
        self._lock = threading.Lock()
        self._next_subscriber_id = 1
        self._subscribers = {}
        self._all_backlog = deque(maxlen=backlog_limit)
        self._operation_backlog = defaultdict(lambda: deque(maxlen=backlog_limit))

    def publish(self, line, operation_id="-"):
        with self._lock:
            self._all_backlog.append(line)
            if operation_id and operation_id != "-":
                self._operation_backlog[operation_id].append(line)
            subscribers = list(self._subscribers.items())

        for _, subscriber in subscribers:
            expected_operation = subscriber["operation_id"]
            if expected_operation and expected_operation != operation_id:
                continue
            try:
                subscriber["queue"].put_nowait(line)
            except queue.Full:
                continue

    def subscribe(self, operation_id=None):
        subscriber_queue = queue.Queue(maxsize=200)
        with self._lock:
            subscriber_id = str(self._next_subscriber_id)
            self._next_subscriber_id += 1
            self._subscribers[subscriber_id] = {
                "queue": subscriber_queue,
                "operation_id": operation_id or None,
            }
            if operation_id:
                backlog = list(self._operation_backlog.get(operation_id, ()))
            else:
                backlog = list(self._all_backlog)
        return subscriber_id, subscriber_queue, backlog

    def unsubscribe(self, subscriber_id):
        with self._lock:
            self._subscribers.pop(subscriber_id, None)


LOG_STREAM_HUB = LogStreamHub()


class LiveLogHandler(logging.Handler):
    def emit(self, record):
        try:
            line = self.format(record)
            operation_id = getattr(record, "operation_id", "-")
            LOG_STREAM_HUB.publish(line, operation_id=operation_id)
        except Exception:
            self.handleError(record)


def configure_logging(log_path):
    root_logger = logging.getLogger()
    if getattr(root_logger, "_vidigo_logging_configured", False):
        return root_logger

    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    formatter = PlainTextFormatter()
    handlers = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(),
        LiveLogHandler(),
    ]

    root_logger.handlers.clear()
    root_logger.setLevel(logging.INFO)

    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(OperationContextFilter())
        root_logger.addHandler(handler)

    root_logger._vidigo_logging_configured = True
    return root_logger


@contextlib.contextmanager
def bind_operation(operation_id):
    token = _operation_id_var.set(operation_id or "-")
    try:
        yield
    finally:
        _operation_id_var.reset(token)


def get_operation_id():
    return _operation_id_var.get() or "-"


def log_message(logger, level, message, stage=None, **variables):
    suffix = _format_variables(variables)
    text = f"{message} | {suffix}" if suffix else message
    logger.log(level, text, extra={"stage": stage or "-"})


def log_info(logger, message, stage=None, **variables):
    log_message(logger, logging.INFO, message, stage=stage, **variables)


def log_warning(logger, message, stage=None, **variables):
    log_message(logger, logging.WARNING, message, stage=stage, **variables)


def log_error(logger, message, stage=None, **variables):
    log_message(logger, logging.ERROR, message, stage=stage, **variables)


def log_exception(logger, message, stage=None, **variables):
    suffix = _format_variables(variables)
    text = f"{message} | {suffix}" if suffix else message
    logger.exception(text, extra={"stage": stage or "-"})
