from collections.abc import Iterable
from datetime import date
from typing import Optional
from uuid import UUID

from .equipment_interval_utils import (
    get_max_concurrent_quantity,
    sort_equipment_reservations,
)
from .equipment_models import (
    EquipmentAllocationRequest,
    EquipmentAvailabilityKey,
    EquipmentInventory,
    EquipmentReservation,
    EquipmentValidationResult,
)


class EquipmentCache:
    """Separate in-memory inventory and quantity-reservation cache for E2 equipment."""

    def __init__(self) -> None:
        self._inventories: dict[UUID, EquipmentInventory] = {}
        self._reservations: dict[
            EquipmentAvailabilityKey,
            list[EquipmentReservation],
        ] = {}

    def set_inventory(self, inventory: EquipmentInventory) -> None:
        """Set or replace inventory; reject reductions that invalidate reservations."""
        replacement = EquipmentInventory.model_validate(inventory)
        existing = self._reservations_for_equipment(replacement.equipment_id)

        for interval_reservations in existing.values():
            if get_max_concurrent_quantity(interval_reservations) > replacement.total_quantity:
                raise ValueError(
                    "inventory reduction would make existing reservations exceed "
                    "available equipment quantity"
                )

        self._inventories[replacement.equipment_id] = replacement

    def replace_inventory(
        self,
        inventory: EquipmentInventory,
    ) -> EquipmentValidationResult:
        try:
            self.set_inventory(inventory)
        except (TypeError, ValueError) as error:
            return EquipmentValidationResult(valid=False, errors=[str(error)])
        return EquipmentValidationResult(valid=True)

    def get_inventory(
        self,
        equipment_id: UUID,
    ) -> Optional[EquipmentInventory]:
        return self._inventories.get(equipment_id)

    def has_inventory(self, equipment_id: UUID) -> bool:
        return equipment_id in self._inventories

    def set_reservations(
        self,
        equipment_id: UUID,
        booking_date: date,
        reservations: Iterable[EquipmentReservation],
    ) -> None:
        inventory = self.get_inventory(equipment_id)
        if inventory is None:
            raise ValueError("inventory is missing for the equipment")

        staged = sort_equipment_reservations(reservations)
        booking_ids: set[UUID] = set()
        for reservation in staged:
            if reservation.equipment_id != equipment_id:
                raise ValueError("reservation equipment ID does not match the cache key")
            if reservation.interval.start.date() != booking_date:
                raise ValueError("reservation date does not match the cache key")
            if reservation.interval.end.date() != booking_date:
                raise ValueError("reservation interval must remain within one date")
            if reservation.booking_id in booking_ids:
                raise ValueError(
                    "duplicate booking reference in an equipment/date cache entry"
                )
            booking_ids.add(reservation.booking_id)

        if get_max_concurrent_quantity(staged) > inventory.total_quantity:
            raise ValueError("reservations exceed equipment inventory")

        self._reservations[(equipment_id, booking_date)] = staged

    def get_reservations(
        self,
        equipment_id: UUID,
        booking_date: date,
    ) -> Optional[list[EquipmentReservation]]:
        reservations = self._reservations.get((equipment_id, booking_date))
        return reservations.copy() if reservations is not None else None

    def has_reservations(
        self,
        equipment_id: UUID,
        booking_date: date,
    ) -> bool:
        return (equipment_id, booking_date) in self._reservations

    def batch_replace_reservations(
        self,
        replacements: dict[tuple[UUID, date], list[EquipmentReservation]],
    ) -> None:
        """Validate every staged cache entry before replacing any entry."""
        staged_cache = {
            key: list(reservations)
            for key, reservations in self._reservations.items()
        }

        for (equipment_id, booking_date), reservations in replacements.items():
            staged_cache[(equipment_id, booking_date)] = list(reservations)

        for (equipment_id, booking_date), reservations in staged_cache.items():
            inventory = self.get_inventory(equipment_id)
            if inventory is None:
                raise ValueError("inventory is missing for the equipment")

            staged = sort_equipment_reservations(reservations)
            booking_ids: set[UUID] = set()
            for reservation in staged:
                if reservation.equipment_id != equipment_id:
                    raise ValueError("reservation equipment ID does not match the cache key")
                if reservation.interval.start.date() != booking_date:
                    raise ValueError("reservation date does not match the cache key")
                if reservation.interval.end.date() != booking_date:
                    raise ValueError("reservation interval must remain within one date")
                if reservation.booking_id in booking_ids:
                    raise ValueError(
                        "duplicate booking reference in an equipment/date cache entry"
                    )
                booking_ids.add(reservation.booking_id)

            if get_max_concurrent_quantity(staged) > inventory.total_quantity:
                raise ValueError("reservations exceed equipment inventory")

        for (equipment_id, booking_date) in list(staged_cache):
            staged_cache[(equipment_id, booking_date)] = sort_equipment_reservations(
                staged_cache[(equipment_id, booking_date)]
            )

        self._reservations = staged_cache

    def replace_reservation_snapshot(
        self,
        reservations: Iterable[EquipmentReservation],
    ) -> EquipmentValidationResult:
        """Atomically replace the complete reservation snapshot.

        The supplied iterable is an authoritative E3-derived full snapshot.
        Inventory entries are preserved. Missing inventory or inconsistent
        reservations make the complete refresh fail without changing state.
        """
        try:
            grouped: dict[
                EquipmentAvailabilityKey,
                list[EquipmentReservation],
            ] = {}
            for item in reservations:
                reservation = EquipmentReservation.model_validate(item)
                if reservation.interval.start.date() != reservation.interval.end.date():
                    raise ValueError(
                        "reservation interval must be contained within one date"
                    )
                key = (
                    reservation.equipment_id,
                    reservation.interval.start.date(),
                )
                grouped.setdefault(key, []).append(
                    reservation.model_copy(deep=True)
                )

            staged_cache: dict[
                EquipmentAvailabilityKey,
                list[EquipmentReservation],
            ] = {
                key: sort_equipment_reservations(items)
                for key, items in grouped.items()
            }

            for (equipment_id, booking_date), items in staged_cache.items():
                inventory = self.get_inventory(equipment_id)
                if inventory is None:
                    raise ValueError(
                        f"inventory is missing for equipment {equipment_id}"
                    )

                booking_ids: set[UUID] = set()
                for reservation in items:
                    if reservation.equipment_id != equipment_id:
                        raise ValueError(
                            "reservation equipment ID does not match the cache key"
                        )
                    if reservation.interval.start.date() != booking_date:
                        raise ValueError(
                            "reservation date does not match the cache key"
                        )
                    if reservation.booking_id in booking_ids:
                        raise ValueError(
                            "duplicate booking reference in an equipment/date "
                            "cache entry"
                        )
                    booking_ids.add(reservation.booking_id)

                if get_max_concurrent_quantity(items) > inventory.total_quantity:
                    raise ValueError(
                        "reservations exceed equipment inventory"
                    )

            self._reservations = staged_cache
        except (TypeError, ValueError) as error:
            return EquipmentValidationResult(
                valid=False,
                errors=[str(error)],
            )
        return EquipmentValidationResult(valid=True)

    def remove_reservations(
        self,
        equipment_id: UUID,
        booking_date: date,
    ) -> None:
        self._reservations.pop((equipment_id, booking_date), None)

    def clear(self) -> None:
        self._inventories.clear()
        self._reservations.clear()

    def copy(self) -> "EquipmentCache":
        """Return an independent staged copy of inventories and reservations."""
        copied = EquipmentCache()
        copied._inventories = dict(self._inventories)
        copied._reservations = {
            key: [
                reservation.model_copy(deep=True)
                for reservation in reservations
            ]
            for key, reservations in self._reservations.items()
        }
        return copied

    def snapshot(self) -> dict[
        EquipmentAvailabilityKey,
        list[EquipmentReservation],
    ]:
        """Return a defensive copy of reservation cache state."""
        return {
            key: [
                reservation.model_copy(deep=True)
                for reservation in reservations
            ]
            for key, reservations in self._reservations.items()
        }

    def restore_reservation_snapshot(
        self,
        snapshot: dict[
            EquipmentAvailabilityKey,
            list[EquipmentReservation],
        ],
    ) -> EquipmentValidationResult:
        """Restore an exact known-good snapshot without invoking replace hooks."""
        try:
            restored: dict[
                EquipmentAvailabilityKey,
                list[EquipmentReservation],
            ] = {}
            for key, reservations in snapshot.items():
                restored[key] = [
                    reservation.model_copy(deep=True)
                    for reservation in reservations
                ]
            self._reservations = restored
        except Exception as error:
            return EquipmentValidationResult(valid=False, errors=[str(error)])
        return EquipmentValidationResult(valid=True)

    def get_reservations_for_booking(
        self,
        booking_id: UUID,
        equipment_id: Optional[UUID] = None,
    ) -> list[EquipmentReservation]:
        matches = [
            reservation
            for (reserved_equipment_id, _), reservations in self._reservations.items()
            if equipment_id is None or reserved_equipment_id == equipment_id
            for reservation in reservations
            if reservation.booking_id == booking_id
        ]
        return sort_equipment_reservations(matches)

    def get_reservations_for_interval(
        self,
        equipment_id: UUID,
        booking_date: date,
        interval_start,
        interval_end,
    ) -> list[EquipmentReservation]:
        reservations = self.get_reservations(equipment_id, booking_date) or []
        return [
            reservation
            for reservation in reservations
            if reservation.interval.start < interval_end
            and interval_start < reservation.interval.end
        ]

    def find_duplicate_booking_reservations(
        self,
        booking_id: UUID,
    ) -> list[EquipmentReservation]:
        return self.get_reservations_for_booking(booking_id)

    def find_reservation_locations(
        self,
        booking_id: UUID,
        equipment_id: Optional[UUID] = None,
    ) -> dict[tuple[UUID, date], list[EquipmentReservation]]:
        locations: dict[
            tuple[UUID, date],
            list[EquipmentReservation],
        ] = {}
        for key, reservations in self._reservations.items():
            if equipment_id is not None and key[0] != equipment_id:
                continue
            matches = [
                reservation
                for reservation in reservations
                if reservation.booking_id == booking_id
            ]
            if matches:
                locations[key] = matches
        return locations

    def _reservations_for_equipment(
        self,
        equipment_id: UUID,
    ) -> dict[EquipmentAvailabilityKey, list[EquipmentReservation]]:
        return {
            key: reservations
            for key, reservations in self._reservations.items()
            if key[0] == equipment_id
        }
