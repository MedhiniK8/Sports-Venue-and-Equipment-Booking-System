
from pathlib import Path
import sys
import asyncio

# Make the backend package importable when running this script.
BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import select

from app.e3_persistence.models import Sport, Court, EquipmentItem
from app.e3_persistence.session import get_session_factory, dispose_engine


# --------------------------------------------------
# INITIAL SPORTS AND COURTS
# Add new sports and their courts here.
# --------------------------------------------------

SPORTS_AND_COURTS = {
    "Badminton": [
        "Badminton Court 1",
        "Badminton Court 2",
    ],
    "Basketball": [
        "Basketball Court 1",
    ],
    "Volleyball": [
        "Volleyball Court 1",
    ],
    "Football": [
        "Football Ground 1",
    ],
    "Tennis": [
        "Tennis Court 1",
    ],
    "Table Tennis": [
        "Table Tennis Room 1",
    ],
    "Kabaddi": [
        "Kabaddi Ground 1",
    ],
}


# --------------------------------------------------
# INITIAL EQUIPMENT INVENTORY
# Add new equipment and quantities here.
# --------------------------------------------------

EQUIPMENT_INVENTORY = {
    "Badminton Racket": 10,
    "Shuttlecock": 50,
    "Basketball": 5,
    "Volleyball": 5,
    "Football": 5,
    "Tennis Racket": 6,
    "Tennis Ball": 30,
    "Table Tennis Bat": 8,
    "Table Tennis Ball": 50,
    "Football Goalkeeper Gloves": 2,
}


async def seed_catalog():
    factory = get_session_factory()

    added_sports = 0
    added_courts = 0
    added_equipment = 0

    async with factory() as session:
        async with session.begin():

            # --------------------------------------
            # 1. Insert missing sports
            # --------------------------------------

            existing_sports = (
                await session.scalars(select(Sport))
            ).all()

            sports_by_name = {
                sport.name: sport
                for sport in existing_sports
            }

            for sport_name in SPORTS_AND_COURTS:
                if sport_name not in sports_by_name:
                    sport = Sport(name=sport_name)
                    session.add(sport)
                    sports_by_name[sport_name] = sport
                    added_sports += 1

            await session.flush()

            # --------------------------------------
            # 2. Insert missing courts
            # --------------------------------------

            for sport_name, court_names in SPORTS_AND_COURTS.items():
                sport = sports_by_name[sport_name]

                existing_courts = (
                    await session.scalars(
                        select(Court).where(
                            Court.sport_id == sport.sport_id
                        )
                    )
                ).all()

                existing_court_names = {
                    court.name for court in existing_courts
                }

                for court_name in court_names:
                    if court_name not in existing_court_names:
                        session.add(
                            Court(
                                sport_id=sport.sport_id,
                                name=court_name,
                            )
                        )
                        existing_court_names.add(court_name)
                        added_courts += 1

            # --------------------------------------
            # 3. Insert missing equipment
            # --------------------------------------

            existing_equipment = (
                await session.scalars(select(EquipmentItem))
            ).all()

            equipment_by_name = {
                item.name: item
                for item in existing_equipment
            }

            for equipment_name, quantity in EQUIPMENT_INVENTORY.items():

                if quantity < 0:
                    raise ValueError(
                        f"Invalid quantity for {equipment_name}"
                    )

                if equipment_name not in equipment_by_name:
                    session.add(
                        EquipmentItem(
                            name=equipment_name,
                            total_quantity=quantity,
                        )
                    )
                    added_equipment += 1

    print("\nCatalog seeding completed successfully!")
    print("---------------------------------------")
    print(f"Sports added:    {added_sports}")
    print(f"Courts added:    {added_courts}")
    print(f"Equipment added: {added_equipment}")
    print("---------------------------------------")
    print("Existing records were left unchanged.")


async def main():
    try:
        await seed_catalog()
    finally:
        await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
