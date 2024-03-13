import asyncio
from navigator.actions.google.models import TravelerSearch, Location
from navigator.actions.google.maps import Route

async def main():
    origin = Location(
        latitude=29.816324,
        longitude=-95.552192
    )
    destination = Location(
        latitude=30.139538,
        longitude=-96.395957
    )
    traveler = TravelerSearch(
        origin=origin,
        destination=destination
    )
    route = Route()
    result = await route.get_route(traveler)
    print(result)

async def optimal_route():
    origin = Location(
        latitude=28.257247,
        longitude=-82.290915
    )
    destination = origin
    locations = [
        {
            "store_id": "LWS0740",
            "location_name": "Lowe's 740 Saint Petersburg FL",
            "latitude": 27.795269,
            "longitude": -82.666681
        },
        {
            "store_id": "LWS1190",
            "location_name": "Lowe's 1190 Pinellas Park FL",
            "latitude": 27.841494,
            "longitude": -82.738243
        },
        {
            "store_id": "LWS1701",
            "location_name": "Lowe's 1701 Largo FL",
            "latitude": 27.895747,
            "longitude": -82.793118
        },
        {
            "store_id": "LWS0771",
            "location_name": "Lowe's 771 Clearwater FL",
            "latitude": 28.016885,
            "longitude": -82.740154
        },
        {
            "store_id": "LWS1714",
            "location_name": "Lowe's 1714 Clearwater FL",
            "latitude": 27.958673,
            "longitude": -82.728782
        },
        {
            "store_id": "LWS2777",
            "location_name": "Lowe's 2777 Tarpon Springs FL",
            "latitude": 28.151765,
            "longitude": -82.741426
        },
        {
            "store_id": "LWS0724",
            "location_name": "Lowe's 724 New Port Richey FL",
            "latitude": 28.278612,
            "longitude": -82.672654
        }
    ]
    traveler = TravelerSearch(
        origin=origin,
        destination=destination,
        locations=locations
    )
    route = Route()
    result = await route.waypoint_route(traveler)
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
    asyncio.run(optimal_route())
