from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from shared.logging.base_logger import BaseLogger


class BaseDatabaseClient:
    def __init__(
        self,
        url: str,
        logger: BaseLogger,
        echo: bool = False,
        echo_pool: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_recycle: int = 1800,
        pool_timeout: int = 30,
    ) -> None:
        self.logger = logger.bind(component="db_client")

        self.engine: AsyncEngine = create_async_engine(
            url=url,
            echo=echo,
            echo_pool=echo_pool,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_recycle=pool_recycle,
            pool_timeout=pool_timeout,
            pool_pre_ping=True,
            isolation_level="READ COMMITTED",
        )

        self.session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            bind=self.engine,
            autoflush=False,
            autocommit=False,
            expire_on_commit=False,
        )

    async def dispose(self) -> None:
        """Закрытие всех соединений (важно при shutdown)"""
        await self.engine.dispose()
        self.logger.info("Database connections disposed")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """
        Контекстная сессия без auto-commit (для ручного управления
        транзакциями в сервисах)
        """
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                self.logger.exception("Session rollback due to error")
                raise

    async def session_getter(self) -> AsyncIterator[AsyncSession]:
        """
        Для FastAPI Depends (без auto-commit!)
        """
        async with self.session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                self.logger.exception("Dependency session rollback")
                raise

    async def health_check(self) -> bool:
        """
        Проверка подключения к БД (для readiness probe)
        """
        try:
            async with self.engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True

        except Exception:
            self.logger.exception("Database health check failed")
            return False
