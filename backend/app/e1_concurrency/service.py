from ..contracts.interfaces import ConcurrencyLockInterface
from ..contracts.booking import LockToken, TimeInterval


class ConcurrencyService(ConcurrencyLockInterface):
    """Foundation interface for asynchronous interval locking."""

    async def acquire(self, interval: TimeInterval, resource_id: str) -> LockToken:
        raise NotImplementedError("E1 interval-lock acquisition is not implemented")

    async def release(self, token: LockToken) -> None:
        raise NotImplementedError("E1 interval-lock release is not implemented")
