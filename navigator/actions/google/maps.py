"""
Google Maps API.

Interface for interacting with Google Maps API.
"""
import requests
import string
import datetime
import urllib.parse
import pytz
import polyline
import aiohttp
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.io.img_tiles as cimgt
from navigator.conf import BASE_DIR, TIMEZONE
from .models import (
    TravelerSearch
)
from .libs import GoogleService

class LocationError(Exception):
    pass


class LocationFinder(GoogleService):
    """ LocationFinder class for finding locations."""
    base_url = "https://maps.googleapis.com/maps/api/geocode/json"

    def extract_location(self, data):
        city = state = state_code = zipcode = None
        try:
            for component in data['address_components']:
                if 'locality' in component['types']:
                    city = component['long_name']
                elif 'administrative_area_level_1' in component['types']:
                    state_code = component['short_name']
                    state = component['long_name']
                elif 'postal_code' in component['types']:
                    zipcode = component['long_name']
        except Exception:
            pass
        return city, state, state_code, zipcode

    async def find_location(self, address: str, complete: bool = False) -> dict:
        params = {
            "address": address,
            "key": self._key_
        }
        response = requests.get(
            self.base_url,
            params=params
        )
        if response.status_code == 200:
            result = response.json()
            if result['status'] == 'OK':
                location = result['results'][0]
                city, state, state_code, zipcode = self.extract_location(
                    location
                )
                if complete is False:
                    location_info = {
                        "latitude": location['geometry']['location']['lat'],
                        "longitude": location['geometry']['location']['lng'],
                        "address": location['formatted_address'],
                        "place_id": location['place_id'],
                        "zipcode": zipcode,
                        "city": city,
                        "state": state,
                        "state_code": state_code
                    }
                else:
                    location_info = {
                        "latitude": location['geometry']['location']['lat'],
                        "longitude": location['geometry']['location']['lng'],
                        "address": location['formatted_address'],
                        "place_id": location['place_id'],
                        "zipcode": zipcode,
                        "city": city,
                        "state": state,
                        "state_code": state_code,
                        **location
                    }
                return location_info
            else:
                raise LocationError(
                    f"Error: {result['status']}: {result!s}"
                )
        else:
            result = {}


class Route(GoogleService):
    """ Route class for generating route maps.

    Offers methods for plotting routes and generating static maps.
    """
    def plot_route(self, decoded_polyline):
        # Generate a unique filename with timestamp
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        output_file = BASE_DIR.joinpath(
            'static', 'maps',
            f'route_map_{timestamp}.png'
        )
        # Set up the map
        fig = plt.figure(figsize=(30, 30))
        ax = plt.axes(projection=ccrs.PlateCarree())
        ax.set_extent(
            [
                min(lon for _, lon in decoded_polyline) - 0.05,
                max(lon for _, lon in decoded_polyline) + 0.05,
                min(lat for lat, _ in decoded_polyline) - 0.05,
                max(lat for lat, _ in decoded_polyline) + 0.05
            ]
        )
        # Add OpenStreetMap imagery
        # stamen_terrain = cimgt.Stamen('terrain-background')
        openstreetmap_tiles = cimgt.OSM()
        # ax.add_image(stamen_terrain, 8)
        ax.add_image(openstreetmap_tiles, 10)
        # Plot the route
        ax.plot([lon for _, lon in decoded_polyline],
                [lat for lat, _ in decoded_polyline],
                color='red', linewidth=3, marker='o',
                transform=ccrs.Geodetic())
        # Save to file
        plt.savefig(output_file, dpi=300)
        print(f"Map saved as: {output_file}")
        return output_file

    def get_google_map(
        self,
        origin,
        destination,
        directions_result,
        payload,
        encoded_polyline,
        locations: list = None
    ):
        # Base URL for Static Maps API
        base_url = "https://maps.googleapis.com/maps/api/staticmap"
        # Size of the resulting map image
        size = payload.map_size
        map_size = f"{size[0]}x{size[1]}"

        # Origin marker (green)
        origin_marker = f"markers=color:green|label:O|{'{:.6f},{:.6f}'.format(*origin)}"
        # Destination marker (same as origin in this case, so it may overlap)
        dest_marker = f"markers=color:red|label:D|{'{:.6f},{:.6f}'.format(*destination)}"

        # Create waypoint markers
        waypoint_markers = []
        waypoint_markers.append(origin_marker)
        waypoint_markers.append(dest_marker)

        if locations:
            waypoint_order = directions_result['routes'][0].get('waypoint_order', [])
            waypoints = [locations[i] for i in waypoint_order]
            # Waypoint markers (blue)
            color_range = [
                "0x0000FF",  # Start (avoid pure blue)
                "0x0033FF",
                "0x0066FF",
                "0x0099FF",
                "0x00CCFF",  # Midpoint (avoid pure blue)
                "0x00FFFF",  # Midpoint (avoid pure white)
                "0xFFCC00",  # Midpoint (avoid pure red)
                "0xFF9900",
                "0xFF6600",
                "0xFF3300",
                "0xFF0000"   # End (avoid pure red)
            ]
            alpha_lower = string.ascii_uppercase
            for i, waypoint in enumerate(waypoints):
                color = color_range[i]
                label = alpha_lower[i]
                lat = waypoint['latitude']
                long = waypoint['longitude']
                waypoint_markers.append(
                    f"markers=color:{color}|size:mid|label:{label}|{lat},{long}"
                )

        # Combine all markers in one parameter
        markers_parameter = '&'.join(
            waypoint_markers
        )

        base_url = "https://maps.googleapis.com/maps/api/staticmap"
        params = {
            "size": map_size,
            "scale": payload.scale,
            "path": f"enc:{encoded_polyline}",
            "maptype": payload.maptype,
            "zoom": payload.zoom,
            "language": "en",
            "key": self._key_
        }
        query_string = urllib.parse.urlencode(params)
        return base_url + "?" + query_string + "&" + markers_parameter

    async def get_route(
        self,
        payload: TravelerSearch,
        complete: bool = False
    ):
        base_url = 'https://maps.googleapis.com/maps/api/directions/json'
        if payload.departure_time != 'now':
            # we need to convert the departure time to a timestamp
            # in seconds since the epoch
            now = datetime.datetime.now(tz=pytz.timezone(TIMEZONE))
            try:
                departure = datetime.datetime.strptime(
                    payload.departure_time, "%Y-%m-%d %H:%M:%S.%f%z"
                )
            except ValueError:
                try:
                    departure = datetime.datetime.strptime(
                        payload.departure_time, '%Y-%m-%dT%H:%M'
                    )
                except ValueError:
                    departure = datetime.datetime.now()
            if departure < now:
                tomorrow = now + datetime.timedelta(days=1)
                departure = departure.replace(
                    year=tomorrow.year,
                    month=tomorrow.month,
                    day=tomorrow.day
                )
            departure_time = int(departure.timestamp())
        else:
            departure_time = 'now'
        origin = (
            payload.origin.latitude,
            payload.origin.longitude
        )
        destination = (
            payload.destination.latitude,
            payload.destination.longitude
        )
        params = {
            'origin': ",".join([str(x) for x in origin]),
            'destination': ",".join([str(x) for x in destination]),
            'key': self._key_,
            'mode': payload.travel_mode,
            'departure_time': departure_time,
            'units': payload.units
        }
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            result = response.json()
            if result['status'] == 'OK':
                # Extracting route, duration, and distance information
                route = result['routes'][0]
                encoded_polyline = route['overview_polyline']['points']
                decoded_polyline = polyline.decode(encoded_polyline)
                map_url = self.get_google_map(
                    origin,
                    destination,
                    result,
                    payload,
                    encoded_polyline,
                    locations=None
                )
                total_duration = 0
                total_distance = 0
                # Duration in seconds
                # Distance in meters
                for leg in route['legs']:
                    total_duration += leg['duration']['value']
                    total_distance += leg['distance']['value']
                # Convert duration to minutes
                total_duration_min = total_duration / 60
                # Convert distance to miles
                total_distance_miles = total_distance / 1609.34
                bestroute = []
                for i, leg in enumerate(route['legs']):
                    step = leg['steps'][0]
                    bestroute.append(
                        f"Leg {i+1}: {step['html_instructions']} for {leg['distance']['text']}"
                    )
                url_map = None
                if decoded_polyline:
                    if payload.open_map is True:
                        url_map = self.plot_route(decoded_polyline)
                # Extract the optimal order of stores:
                response = {
                    "route_legs": bestroute,
                    "duration": total_duration_min,
                    "distance": total_distance_miles,
                    "total_duration": f"{total_duration_min:.2f} minutes",
                    "total_distance": f"{total_distance_miles:.2f} miles",
                    "map_url": map_url,
                    "map": url_map,
                    "overview": decoded_polyline
                }
                if complete is True:
                    response['response'] = result
                return response

    async def waypoint_route(
        self,
        payload: TravelerSearch,
        complete: bool = False
    ):
        locations_list = []
        locations = payload.locations
        for store in locations:
            position = (store['latitude'], store['longitude'])
            locations_list.append(position)

        base_url = 'https://maps.googleapis.com/maps/api/directions/json'
        if payload.departure_time != 'now':
            # we need to convert the departure time to a timestamp
            # in seconds since the epoch
            now = datetime.datetime.now(tz=pytz.timezone(TIMEZONE))
            try:
                departure = datetime.datetime.strptime(
                    payload.departure_time, "%Y-%m-%d %H:%M:%S.%f%z"
                )
            except ValueError:
                try:
                    departure = datetime.datetime.strptime(
                        payload.departure_time, '%Y-%m-%dT%H:%M'
                    )
                except ValueError:
                    departure = datetime.datetime.now()
            if departure < now:
                tomorrow = now + datetime.timedelta(days=1)
                departure = departure.replace(
                    year=tomorrow.year,
                    month=tomorrow.month,
                    day=tomorrow.day
                )
            departure_time = int(departure.timestamp())
        else:
            departure_time = 'now'
        origin = (
            payload.origin.latitude,
            payload.origin.longitude
        )
        destination = (
            payload.destination.latitude,
            payload.destination.longitude
        )
        params = {
            'origin': ",".join([str(x) for x in origin]),
            'destination': ",".join([str(x) for x in destination]),
            'key': self._key_,
            'waypoints': '',
            'mode': payload.travel_mode,
            'departure_time': departure_time,
            'units': payload.units
        }
        if payload.optimal is True:
            params['waypoints'] = "optimize:true|"
        params['waypoints'] += "|".join(
            [",".join([str(x) for x in loc]) for loc in locations_list]
        )
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.request('GET', base_url, params=params) as response:
                if response.status == 200:
                    result = await response.json()
            if result['status'] == 'OK':
                # Extracting route, duration, and distance information
                route = result['routes'][0]
                encoded_polyline = route['overview_polyline']['points']
                decoded_polyline = polyline.decode(encoded_polyline)
                map_url = self.get_google_map(
                    origin,
                    destination,
                    result,
                    payload,
                    encoded_polyline,
                    locations=locations
                )
                total_duration = 0
                total_distance = 0
                # Duration in seconds
                # Distance in meters
                for leg in route['legs']:
                    total_duration += leg['duration']['value']
                    total_distance += leg['distance']['value']
                # Convert duration to minutes
                total_duration_min = total_duration / 60
                # Convert distance to miles
                total_distance_miles = total_distance / 1609.34
                bestroute = []
                for i, leg in enumerate(route['legs']):
                    step = leg['steps'][0]
                    bestroute.append(
                        f"Leg {i+1}: {step['html_instructions']} for {leg['distance']['text']}"
                    )
                url_map = None
                if decoded_polyline:
                    if payload.open_map is True:
                        url_map = self.plot_route(decoded_polyline)
                # Extract the optimal order of stores:
                waypoint_order = route['waypoint_order']
                route = [locations[i]['store_id'] for i in waypoint_order]
                response = {
                    "route_legs": bestroute,
                    "route": route,  # The ordered list of store IDs
                    "duration": total_duration_min,
                    "distance": total_distance_miles,
                    "total_duration": f"{total_duration_min:.2f} minutes",
                    "total_distance": f"{total_distance_miles:.2f} miles",
                    "map_url": map_url,
                    "map": url_map,
                    # "route_overview": decoded_polyline
                }
                if complete is True:
                    response['response'] = result
                return response
