"""Add reproducible, capacity-aware inventory for the travel demo."""

from __future__ import annotations

from datetime import date, timedelta

from common import session

FLIGHTS_TABLE = "agente-agente-viajes-flights"
HOTELS_TABLE = "agente-agente-viajes-hotels"
START_DATE = date(2026, 9, 9)
DAYS = 12

FLIGHT_ROUTES = (
    ("EZE", "MDZ", 95, "Andes Air"),
    ("AEP", "MDZ", 105, "Río Plata Air"),
    ("MDZ", "EZE", 98, "Andes Air"),
    ("MDZ", "AEP", 108, "Río Plata Air"),
)
HOTEL_NAMES = ("Casa Andina", "Bodega Stay", "Cordillera Suites")


def update_existing_capacity(table) -> int:
    response = table.scan()
    items = response["Items"]
    while response.get("LastEvaluatedKey"):
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response["Items"])
    for index, item in enumerate(items):
        table.update_item(
            Key={"route": item["route"], "departureDateFlightId": item["departureDateFlightId"]},
            UpdateExpression="SET #capacity = :capacity, availableSeats = :seats",
            ExpressionAttributeNames={"#capacity": "capacity"},
            ExpressionAttributeValues={":capacity": 180, ":seats": 28 + (index * 7) % 112},
        )
    return len(items)


def add_flights(table) -> int:
    count = 0
    for day_offset in range(DAYS):
        departure_date = START_DATE + timedelta(days=day_offset)
        for route_index, (origin, destination, base_price, airline) in enumerate(FLIGHT_ROUTES):
            for service_index, (stops, departure_time) in enumerate(((0, "07:15"), (1, "15:40"))):
                flight_number = 1001 + day_offset * 8 + route_index * 2 + service_index
                available_seats = 0 if (day_offset + route_index + service_index) % 17 == 0 else 12 + (day_offset * 13 + route_index * 19 + service_index * 23) % 146
                flight_id = f"flight-demo-{flight_number}"
                table.put_item(
                    Item={
                        "route": f"{origin}#{destination}",
                        "departureDateFlightId": f"{departure_date.isoformat()}#{flight_id}",
                        "flightId": flight_id,
                        "origin": origin,
                        "destination": destination,
                        "departureDate": departure_date.isoformat(),
                        "departureTime": departure_time,
                        "arrivalTime": "09:00" if stops == 0 else "18:10",
                        "airline": airline,
                        "flightNumber": f"{airline[:2].upper()}{flight_number}",
                        "stops": stops,
                        "price": base_price + day_offset * 3 + service_index * 52,
                        "currency": "USD",
                        "capacity": 180,
                        "availableSeats": available_seats,
                    }
                )
                count += 1
    return count


def update_existing_hotel_capacity(table) -> int:
    response = table.scan()
    items = response["Items"]
    while response.get("LastEvaluatedKey"):
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response["Items"])
    for index, item in enumerate(items):
        table.update_item(
            Key={"destination": item["destination"], "checkInHotelId": item["checkInHotelId"]},
            UpdateExpression="SET maxGuests = :guests, roomsAvailable = :rooms",
            ExpressionAttributeValues={":guests": item["guests"], ":rooms": 1 + index % 5},
        )
    return len(items)


def add_hotels(table) -> int:
    count = 0
    for day_offset in range(DAYS):
        check_in = START_DATE + timedelta(days=day_offset)
        for nights in (3, 4, 5):
            for hotel_index, (name, max_guests) in enumerate(zip(HOTEL_NAMES, (2, 3, 4), strict=True)):
                hotel_id = f"hotel-mdz-{check_in:%Y%m%d}-{nights}n-{max_guests}p"
                rooms_available = 0 if (day_offset + nights + hotel_index) % 19 == 0 else 1 + (day_offset + hotel_index) % 5
                table.put_item(
                    Item={
                        "destination": "MDZ",
                        "checkInHotelId": f"{check_in.isoformat()}#{hotel_id}",
                        "hotelId": hotel_id,
                        "name": f"{name} {hotel_index + 1}",
                        "destinationName": "Mendoza",
                        "checkIn": check_in.isoformat(),
                        "checkOut": (check_in + timedelta(days=nights)).isoformat(),
                        "nights": nights,
                        "guests": max_guests,
                        "maxGuests": max_guests,
                        "roomsAvailable": rooms_available,
                        "pricePerNight": 62 + hotel_index * 17 + nights * 4 + day_offset * 2,
                        "rating": 3 + (hotel_index + day_offset) % 3,
                        "currency": "USD",
                    }
                )
                count += 1
    return count


def main() -> None:
    dynamodb = session().resource("dynamodb")
    existing_flights = update_existing_capacity(dynamodb.Table(FLIGHTS_TABLE))
    new_flights = add_flights(dynamodb.Table(FLIGHTS_TABLE))
    existing_hotels = update_existing_hotel_capacity(dynamodb.Table(HOTELS_TABLE))
    new_hotels = add_hotels(dynamodb.Table(HOTELS_TABLE))
    print(f"Updated {existing_flights} existing flights; added {new_flights} flights.")
    print(f"Updated {existing_hotels} existing hotels; added {new_hotels} hotels.")


if __name__ == "__main__":
    main()
