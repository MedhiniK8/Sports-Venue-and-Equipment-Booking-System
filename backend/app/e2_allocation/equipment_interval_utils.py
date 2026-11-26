from collections.abc import Iterable, Sequence
from datetime import datetime

from ..contracts.booking import TimeInterval
from .equipment_models import (
    EquipmentAvailabilitySegment,
    EquipmentReservation,
)


def sort_equipment_reservations(
    reservations: Iterable[EquipmentReservation],
) -> list[EquipmentReservation]:
    return sorted(reservations, key=lambda reservation: reservation.interval.start)


def find_overlapping_equipment_reservations(
    reservations: Sequence[EquipmentReservation],
    requested_interval: TimeInterval,
) -> list[EquipmentReservation]:
    return [
        reservation
        for reservation in reservations
        if reservation.interval.start < requested_interval.end
        and requested_interval.start < reservation.interval.end
    ]


def get_max_concurrent_quantity(
    reservations: Sequence[EquipmentReservation],
) -> int:
    if not reservations:
        return 0

    boundaries = sorted(
        {
            boundary
            for reservation in reservations
            for boundary in (
                reservation.interval.start,
                reservation.interval.end,
            )
        }
    )
    maximum = 0
    for start, end in zip(boundaries, boundaries[1:]):
        if start >= end:
            continue
        reserved = sum(
            reservation.quantity
            for reservation in reservations
            if reservation.interval.start <= start
            and reservation.interval.end >= end
        )
        maximum = max(maximum, reserved)
    return maximum


def calculate_equipment_availability_segments(
    inventory_quantity: int,
    reservations: Sequence[EquipmentReservation],
    requested_interval: TimeInterval,
) -> list[EquipmentAvailabilitySegment]:
    overlapping = find_overlapping_equipment_reservations(
        reservations,
        requested_interval,
    )
    boundaries = sorted(
        {
            requested_interval.start,
            requested_interval.end,
            *[
                point
                for reservation in overlapping
                for point in (
                    max(reservation.interval.start, requested_interval.start),
                    min(reservation.interval.end, requested_interval.end),
                )
            ],
        }
    )

    segments: list[EquipmentAvailabilitySegment] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if start >= end:
            continue
        reserved_quantity = sum(
            reservation.quantity
            for reservation in overlapping
            if reservation.interval.start <= start
            and reservation.interval.end >= end
        )
        available_quantity = max(inventory_quantity - reserved_quantity, 0)
        segments.append(
            EquipmentAvailabilitySegment(
                interval=TimeInterval(start=start, end=end),
                reserved_quantity=reserved_quantity,
                available_quantity=available_quantity,
            )
        )
    return segments


def get_minimum_available_quantity(
    segments: Sequence[EquipmentAvailabilitySegment],
) -> int:
    if not segments:
        return 0
    return min(segment.available_quantity for segment in segments)
