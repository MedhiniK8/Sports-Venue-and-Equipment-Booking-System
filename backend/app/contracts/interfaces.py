
from abc import ABC, abstractmethod

from .booking import (
    LockToken,
    TimeInterval,
    TransactionResult,
    ValidationResult,
)
from uuid import UUID


class ConcurrencyLockInterface(ABC):

    @abstractmethod
    async def acquire(
        self,
        interval: TimeInterval,
        resource_id: str,
    ) -> LockToken:
        raise NotImplementedError

    @abstractmethod
    async def release(self, token: LockToken) -> None:
        raise NotImplementedError


class AllocationInterface(ABC):

    @abstractmethod
    async def validate_time_slot(
        self,
        court_id: UUID,
        equipment_id: UUID | None,
        interval: TimeInterval,
    ) -> ValidationResult:
        raise NotImplementedError

    @abstractmethod
    async def generate_calendar(
        self,
        interval: TimeInterval,
    ) -> list[TimeInterval]:
        raise NotImplementedError

    @abstractmethod
    async def process_post_commit_split_merge(
        self,
        transaction: TransactionResult,
    ) -> list[TimeInterval]:
        raise NotImplementedError
