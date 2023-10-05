from datetime import datetime
from dataclasses import is_dataclass
from asyncdb.models import Model, Column


class Airport(Model):
    iata: str = Column(primary_key=True, required=True)
    airport: str = Column(required=True)
    city: str
    country: str
    created_by: int
    created_at: datetime = Column(default=datetime.now(), repr=False)

    class Meta:
        name: str = 'airports'
        schema = 'public'
        strict = True


if __name__ == '__main__':
    print('ES DATACLASS > ', is_dataclass(Airport))
