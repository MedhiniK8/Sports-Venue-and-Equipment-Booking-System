from typing import Protocol


class PersistenceRepository(Protocol):
    """Placeholder interface owned exclusively by E3."""

    async def execute(self) -> None:
        raise NotImplementedError("E3 repository operations are not implemented")
