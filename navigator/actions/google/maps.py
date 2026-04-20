"""
Google Maps API.

Interface for interacting with Google Maps API.
"""
import string
import datetime
from datetime import timezone
import urllib.parse
import requests
import pytz
import polyline
import aiohttp
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import cartopy.crs as ccrs
import cartopy.io.img_tiles as cimgt
from ...conf import BASE_DIR, TIMEZONE
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

    def get_gradient_colors(
        self,
        num_colors: int = 10,
        start_color: str = '0x0000FF',
        end_color: str = '0xFF0000'
    ):
        """Generating a list of gradient colors.
        """
        start_color = start_color.replace('0x', '#')
        end_color = end_color.replace('0x', '#')
        start_rgb = mcolors.hex2color(start_color)
        end_rgb = mcolors.hex2color(end_color)
        # generate a gradient of colors
        # Create a colormap
        cmap = mcolors.LinearSegmentedColormap.from_list(
            "custom_gradient", [start_rgb, end_rgb]
        )
        # Generate the gradient
        gradient = [
            mcolors.to_hex(cmap(i / (num_colors - 1))) for i in range(num_colors)
        ]
        gradient = [color.upper().replace('#', '0x') for color in gradient]
        return gradient

    def get_google_map(
        self,
        origin,
        destination,
        directions_result,
        payload,
        encoded_polyline,
        locations: list = None,
        # Default colors for the gradient
        start_color: str = "0x0000FF",
        end_color: str = "0xFF0000"
    ):
        # Base URL for Static Maps API
        base_url = "https://maps.googleapis.com/maps/api/staticmap"
        # Size of the resulting map image
        size = payload.map_size
        map_size = f"{size[0]}x{size[1]}"

        # Origin marker (green)
        origin_marker = f"markers=color:green|label:O|{'{:.6f},{:.6f}'.format(*origin)}"
        # Destination marker (if are the same as origin, so it may overlap)
        dest_marker = f"markers=color:red|label:D|{'{:.6f},{:.6f}'.format(*destination)}"

        # Create waypoint markers
        waypoint_markers = [origin_marker, dest_marker]
        # Use the passed locations parameter or fall back to payload.locations
        if waypoint_locations := locations or payload.locations:
            route_data = directions_result['routes'][0]
            # Updated field name for new Routes API
            waypoint_order = route_data.get(
                'optimizedIntermediateWaypointIndex', []
            ) or list(range(len(waypoint_locations)))
            # Extract waypoint coordinates in the optimized order
            waypoints = []
            for i in waypoint_order:
                if i < len(waypoint_locations):
                    waypoint = waypoint_locations[i]
                    coords = waypoint.get_coordinates()
                    waypoints.append(coords)
            num_waypoints = len(waypoints)
            if num_waypoints > 0:
                try:
                    color_range = self.get_gradient_colors(
                        num_waypoints,
                        start_color,
                        end_color
                    )
                except ZeroDivisionError:
                    color_range = self.get_gradient_colors(
                        10,
                        start_color,
                        end_color
                    )
                alpha_upper = string.ascii_uppercase
                for i, waypoint in enumerate(waypoints):
                    if i < len(color_range) and i < len(alpha_upper):
                        color = color_range[i]
                        label = alpha_upper[i]
                        lat = waypoint[0]
                        lng = waypoint[1]
                        waypoint_markers.append(
                            f"markers=color:{color}|size:mid|label:{label}|{lat},{lng}"
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
        return f"{base_url}?{query_string}&{markers_parameter}"

    async def get_route(
        self,
        payload: TravelerSearch,
        complete: bool = True,
        add_overview: bool = True
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
                )
                total_duration = 0
                total_distance = 0
                # Duration in seconds
                # Distance in meters
                for leg in route['legs']:
                    total_duration += leg['duration']['value']
                    total_distance += leg['distance']['value']
                # Convert duration to minutes
                try:
                    total_duration_min = total_duration / 60
                except ZeroDivisionError:
                    total_duration_min = 0
                # Convert distance to miles
                try:
                    total_distance_miles = total_distance / 1609.34
                except ZeroDivisionError:
                    total_distance_miles = 0
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
                    "map": url_map
                }
                if add_overview:
                    response['overview'] = decoded_polyline
                if complete:
                    response['response'] = result
                return response

    def _compute_departure(self, departure_time: datetime):
        """Compute the departure time in seconds since the epoch."""
        if departure_time.tzinfo is None:
            departure_time = departure_time.replace(tzinfo=timezone.utc)
        else:
            # if not, we need to convert it to UTC
            departure_time = departure_time.astimezone(timezone.utc)
        return departure_time

    async def waypoint_route(
        self,
        payload: TravelerSearch,
        complete: bool = True,
        add_overview: bool = True
    ):
        base_url = "https://routes.googleapis.com/directions/v2:computeRoutes"
        departure_time = None
        if payload.departure_time is not None:
            # Google Maps API requires departure_time to be in seconds since the epoch
            # if the departure time is in the past, we need to set it to tomorrow
            now = datetime.datetime.now(tz=timezone.utc)
            tomorrow = now + datetime.timedelta(days=1)
            departure_time = self._compute_departure(payload.departure_time)
            # if the departure time is in the past, we need to set it to tomorrow
            if departure_time < now:
                # Traffic information is only available for future and current times
                # Try setting the year to the current year
                adjusted_dt_utc = departure_time.replace(year=tomorrow.year)
                # If it's still in the past
                # (e.g., user_dt was Jan 1, 2024,
                # now is May 30, 2025 -> adjusted_dt becomes Jan 1, 2025, which is still past)
                if adjusted_dt_utc < now:
                    adjusted_dt_utc = adjusted_dt_utc.replace(year=tomorrow.year + 1)
                departure_time = adjusted_dt_utc
            # we need to convert the departure time to a timestamp
            # in seconds since the epoch
            departure_time = departure_time.strftime('%Y-%m-%dT%H:%M:%SZ')

        origin = payload.origin.get_location()
        destination = payload.destination.get_location()
        data = {
            "origin": origin,
            "destination": destination,
            "travelMode": payload.travel_mode,
            "routingPreference": payload.routing_preference or "TRAFFIC_AWARE",
            "computeAlternativeRoutes": False,
            "optimizeWaypointOrder": False,
            "routeModifiers": {
                "avoidTolls": False,
                "avoidHighways": False,
                "avoidFerries": False
            },
            "languageCode": "en-US",
            "units": payload.units.upper()
        }
        if data['routingPreference'] == 'TRAFFIC_AWARE_OPTIMAL':
            data['trafficModel'] = payload.traffic_model.upper() or 'BEST_GUESS'

        if departure_time is not None:
            data['departureTime'] = departure_time

        if payload.locations:
            data['intermediates'] = [loc.get_location() for loc in payload.locations]
            if payload.optimal is True:
                data['optimizeWaypointOrder'] = True
        # Logging the parameters before sending the request can be very helpful for debugging
        self._logger.notice(
            f"Google Directions API params: {data}"
        )
        timeout = aiohttp.ClientTimeout(total=60)
        result = {}
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._key_,
            "X-Goog-FieldMask": "routes.legs,routes.duration,routes.staticDuration,routes.distanceMeters,routes.polyline,routes.optimizedIntermediateWaypointIndex,routes.description,routes.warnings,routes.viewport,routes.travelAdvisory,routes.localizedValues"  # noqa: E501
        }
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.request('POST', base_url, json=data) as response:
                # check for errors:
                if response.status != 200:
                    error = await response.json()
                    msg = error.get('error', {}).get('message', 'Unknown error')
                    self._logger.error(
                        f"Google Directions API request failed with status: {response.status}"
                    )
                    return {
                        "error": f"Google Directions API request failed with status: {response.status}",
                        "message": msg
                    }
                result = await response.json()
            # The Routes API returns an empty JSON object {} for some error cases (e.g. UNKNOWN_ERROR)
            # even with HTTP 200, so check for presence of 'routes'.
            if not result or 'routes' not in result or not result['routes']:
                self._logger.error(
                    f"Google Routes API returned a 200 OK but no routes found or empty response: {result!r}"
                )
                return {
                    "error": "No routes found in API response or empty response.",
                    "message": "The API returned a successful status but no route data."
                }
            if result.get('routes'):
                # Extracting route, duration, and distance information
                route = result['routes'][0]
                # Get the encoded polyline from the new format
                encoded_polyline = ""
                decoded_polyline = None
                if route.get('polyline') and route['polyline'].get('encodedPolyline'):
                    encoded_polyline = route['polyline']['encodedPolyline']
                    decoded_polyline = polyline.decode(encoded_polyline)
                map_url = self.get_google_map(
                    payload.origin.get_coordinates(),
                    payload.destination.get_coordinates(),
                    result,
                    payload,
                    encoded_polyline
                )
                total_duration = 0
                static_duration = 0
                total_duration_min = 0
                static_duration_min = 0
                total_distance = 0
                total_distance_miles = 0
                # Duration in seconds
                # Distance in meters and extract route instructions:
                bestroute = []
                for i, leg in enumerate(route['legs']):
                    duration_str = leg.get('duration', '0s')
                    total_duration_seconds = int(duration_str.rstrip('s')) if duration_str else 0
                    total_duration += total_duration_seconds
                    # Static Duration (without traffic) for reference
                    static_duration_str = leg.get('staticDuration', '0s')
                    static_duration += int(static_duration_str.rstrip('s'))
                    # Distance:
                    distance_meters = leg.get('distanceMeters', 0)
                    distance_miles = distance_meters / 1609.34 if distance_meters else 0
                    total_distance += distance_meters
                    if leg.get('steps') and len(leg['steps']) > 0:
                        # Get the first step's navigation instruction
                        first_step = leg['steps'][0]
                        if 'navigationInstruction' in first_step:
                            instruction = first_step['navigationInstruction'].get('instructions', '')
                            # Get localized distance for this leg
                            leg_distance = leg.get(
                                'localizedValues', {}
                            ).get('distance', {}).get('text', f"{distance_miles:.1f} mi")  # noqa: E501
                            bestroute.append(f"Leg {i+1}: {instruction} for {leg_distance}")
                        else:
                            # Fallback if no navigation instruction
                            leg_distance = leg.get(
                                'localizedValues', {}
                            ).get('distance', {}).get('text', f"{distance_miles:.1f} mi")  # noqa: E501
                            bestroute.append(f"Leg {i+1}: Continue for {leg_distance}")
                # Convert duration to minutes
                total_duration_min = total_duration / 60 if total_duration > 0 else 0
                static_duration_min = static_duration / 60 if static_duration > 0 else 0
                # Convert distance to miles
                total_distance_miles = total_distance / 1609.34 if total_distance > 0 else 0
                # Generate Route Map if requested:
                url_map = None
                if decoded_polyline and payload.open_map is True:
                    url_map = self.plot_route(decoded_polyline)
                # Extract the optimal order of waypoints if available
                waypoint_order = route.get('optimizedIntermediateWaypointIndex', [])
                # Create the route list based on waypoint order
                locations = payload.locations or []
                try:
                    if waypoint_order:
                        route = [locations[i]['store_id'] for i in waypoint_order]
                    else:
                        # If no optimization was requested, maintain original order
                        route = [loc['store_id'] for loc in locations] if locations else []
                except (AttributeError, KeyError):
                    try:
                        if waypoint_order:
                            route = [locations[i]['location_name'] for i in waypoint_order]
                        else:
                            route = [loc['location_name'] for loc in locations] if locations else []
                    except (AttributeError, KeyError):
                        route = []
                response = {
                    "route_legs": bestroute,
                    "route": route,  # The ordered list of store IDs
                    "duration": total_duration_min,
                    "distance": total_distance_miles,
                    "static_duration": static_duration_min,
                    "total_duration": f"{total_duration_min:.2f} minutes",
                    "total_distance": f"{total_distance_miles:.2f} miles",
                    "map_url": map_url,
                    "map": url_map
                }
                if add_overview:
                    response['overview'] = decoded_polyline
                if complete:
                    response['response'] = result
                return response
