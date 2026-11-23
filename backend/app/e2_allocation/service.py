from ..contracts.booking import TimeInterval, TransactionResult, ValidationResult
from ..contracts.interfaces import AllocationInterface


class AllocationService(AllocationInterface):
    """Foundation interface for validation and allocation processing."""

    async def validate_time_slot(self, interval: TimeInterval) -> ValidationResult:
        raise NotImplementedError("E2 time-slot validation is not implemented")

    async def generate_calendar(self, interval: TimeInterval) -> list[TimeInterval]:
        raise NotImplementedError("E2 calendar generation is not implemented")

    async def process_post_commit_split_merge(
        self, transaction: TransactionResult
    ) -> list[TimeInterval]:
        raise NotImplementedError("E2 post-commit split/merge processing is not implemented")
