import logging
import sys
from threading import Lock
from typing import Any

import structlog
from structlog.typing import FilteringBoundLogger

_CONFIGURED = False
_LOCK = Lock()


def _setup(level: int, dev: bool = False) -> None:
    """
    Глобальная настройка structlog и стандартного logging.

    Вызывается автоматически при создании первого BaseLogger.
    Конфигурация применяется один раз на процесс (thread-safe).

    :param level: Уровень логирования (logging.INFO, DEBUG и т.д.)
    :param dev:   Если True — используется человекочитаемый вывод (ConsoleRenderer).
                  Если False — JSON (для Loki / ELK / продакшена).

    Где использовать:
        Вызывать вручную не нужно — вызывается внутри BaseLogger.
    """
    global _CONFIGURED

    if _CONFIGURED:
        return

    with _LOCK:
        if _CONFIGURED:
            return

        logging.basicConfig(
            format="%(message)s",
            stream=sys.stdout,
            level=level,
        )

        renderer = (
            structlog.dev.ConsoleRenderer()
            if dev
            else structlog.processors.JSONRenderer()
        )

        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.ExceptionRenderer(),
                renderer,
            ],
            wrapper_class=structlog.make_filtering_bound_logger(level),
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

        _CONFIGURED = True


class BaseLogger:
    """
    Базовый структурированный логгер для микросервисов.

    Использует structlog и поддерживает:
    - JSON-логи (для Loki / ELK)
    - contextvars (request_id, trace_id)
    - привязку контекста через bind()

    Каждый лог автоматически содержит поле `service`.

    Пример использования::

        logger = BaseLogger("auth-service")

        logger.info("User created", user_id=1)

        # Добавление контекста
        req_logger = logger.bind(request_id="abc-123")
        req_logger.warning("Invalid token")
    """

    def __init__(
        self,
        service_name: str,
        level: int = logging.INFO,
        dev: bool = False,
    ) -> None:
        """
        :param service_name: Имя сервиса (например "auth", "catalog").
                             Добавляется в каждую запись как поле `service`.
        :param level:        Уровень логирования.
        :param dev:          Включает человекочитаемый вывод вместо JSON.

        Где использовать:
            Создаётся один раз при старте приложения (singleton на сервис).
        """
        _setup(level, dev)

        self.service_name = service_name
        self._logger: FilteringBoundLogger = structlog.get_logger(service_name).bind(
            service=service_name
        )

    def bind(self, **context: Any) -> BaseLogger:
        """
        Создать новый логгер с дополнительным контекстом.

        Контекст добавляется ко всем последующим логам,
        оригинальный логгер при этом не изменяется.

        :param context: Любые ключ-значение (request_id, user_id, component и т.д.)

        :return: Новый экземпляр BaseLogger с добавленным контекстом

        Где использовать:
            - В middleware (request_id, trace_id)
            - В слоях приложения (component="database")
            - В бизнес-логике (user_id, order_id)

        Пример::

            req_logger = logger.bind(request_id="abc-123")
            req_logger.info("Request started")

            db_logger = req_logger.bind(component="database")
            db_logger.error("Query failed")
        """
        instance = BaseLogger.__new__(BaseLogger)
        instance.service_name = self.service_name
        instance._logger = self._logger.bind(**context)
        return instance

    def debug(self, event: str, **kwargs: Any) -> None:
        """
        Логировать отладочное сообщение (DEBUG).

        Используется для детальной диагностики:
        SQL-запросы, внутренние состояния, отладка.

        Пример::

            logger.debug("Cache hit", key="user:1")
        """
        self._logger.debug(event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        """
        Логировать информационное сообщение (INFO).

        Основной уровень логирования в продакшене:
        бизнес-события, операции пользователя.

        Пример::

            logger.info("User created", user_id=1)
        """
        self._logger.info(event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """
        Логировать предупреждение (WARNING).

        Используется для не критичных проблем:
        некорректные данные, fallback-логика.

        Пример::

            logger.warning("Invalid input", field="email")
        """
        self._logger.warning(event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """
        Логировать ошибку (ERROR) с traceback.

        Используется для ошибок, которые не ломают сервис полностью,
        но требуют внимания.

        Пример::

            logger.error("Failed to process payment", order_id=123)
        """
        self._logger.error(event, exc_info=True, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        """
        Логировать критическую ошибку (CRITICAL).

        Используется для серьёзных сбоев:
        падение сервиса, недоступность БД и т.д.

        Пример::

            logger.critical("Database unavailable")
        """
        self._logger.critical(event, **kwargs)

    def exception(self, event: str, **kwargs: Any) -> None:
        """
        Логировать исключение с полным traceback.

        Использовать ТОЛЬКО внутри except-блоков.

        Пример::

            try:
                ...
            except Exception:
                logger.exception("Unexpected error")
        """
        self._logger.exception(event, **kwargs)
