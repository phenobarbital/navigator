from typing import Union
from datamodel import BaseModel, Field


class Location(BaseModel):
    location_name: str = Field(required=False)
    latitude: float = Field(required=False, label="Latitude")
    longitude: float = Field(required=False, label="Longitude")
    address: str = Field(required=False, label="Address")
    place_id: str = Field(required=False)
    formatted_address: str = Field(required=False)

    class Meta:
        strict: bool = True
        title: str = "Location"


class StoreLocation(Location):
    store_id: str = Field(
        required=False,
        ui_widget="input",
        label="Store ID"
    )
    store_name: str = Field(
        required=False,
        ui_widget="input",
        label="Store Name"
    )

    class Meta:
        strict: bool = True
        title: str = "Search for Store by Address"
        settings: dict = {
            "showSubmit": True,
            "SubmitLabel": "Search Store by Address",
            "showCancel": True,
        }


class TravelerSearch(BaseModel):
    origin: Union[Location, StoreLocation] = Field(required=False)
    destination: Union[Location, StoreLocation] = Field(required=False)
    locations: list = Field(required=False, default_factory=list)
    associate_oid: str = Field(required=False)
    open_map: bool = Field(required=False, default=False)
    departure_time: str = Field(required=False, default="now")
    travel_mode: str = Field(required=False, default="driving")
    units: str = Field(required=False, default="imperial")
    optimal: bool = Field(required=False, default=True)
    map_size: tuple = Field(required=False, default=(600, 600))
    scale: int = Field(required=False, default=1)
    zoom: int = Field(required=False, default=9)
    maptype: str = Field(required=False, default="roadmap")

    class Meta:
        strict: bool = True
        title: str = "Search Route"
        settings: dict = {
            "showSubmit": True,
            "SubmitLabel": "Search my Route"
        }
