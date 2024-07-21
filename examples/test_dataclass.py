from datetime import datetime
from dataclasses import is_dataclass
from asyncdb.models import Model, Column


class Airport(Model):
    iata: str = Column(
        primary_key=True, required=True, label="IATA"
    )
    airport: str = Column(
        required=True, label="airport"
    )
    city: str = Column(
        required=False, label="city"
    )
    country: str = Column(
        required=False, label="country"
    )
    created_by: int = Column(
        required=False, label="created_by"
    )
    created_at: datetime = Column(
        default=datetime.now, repr=False, label="created_at"
    )

    class Meta:
        name: str = 'airports'
        schema = 'public'
        strict = True


if __name__ == '__main__':
    print('ES DATACLASS > ', is_dataclass(Airport))
