from datetime import datetime
from asyncdb.models import Model, Column
from navigator_auth import AuthHandler
from navigator import Application
from navigator.views import ModelView
from navigator.ext.locale import LocaleSupport

app = Application()
session = AuthHandler()
session.setup(app)

# support localization:
l18n = LocaleSupport(
    localization=['en_US', 'es_ES', 'es', 'it_IT', 'de_DE', 'fr_FR', 'zh_CN'],
    domain='nav'
)
l18n.setup(app)


class Airport(Model):
    iata: str = Column(
        primary_key=True, required=True, label="IATA"
    )
    airport: str = Column(
        required=True, label="airport", description="Airport"
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
        default=datetime.now, repr=False, label="created_at", description='date_creation'
    )

    class Meta:
        name: str = 'airports'
        schema = 'public'
        description: str = 'Airports Table'
        title: str = 'List of Airports'
        strict = True

class AirportHandler(ModelView):
    model: Model = Airport
    pk: str = 'iata'
    to_locale: list = ['label', 'description' ]

    async def _get_created_by(self, value, column, **kwargs):
        return await self.get_userid(session=self._session)

    async def on_startup(self, *args, **kwargs):
        print(args, kwargs)
        print('THIS CODE RUN ON STARTUP')

    async def on_shutdown(self, *args, **kwargs):
        print('ESTO OCURRE CUANDO SE DETIENE ==== ')

## two required handlers for a ModelHandler.
AirportHandler.configure(app, '/api/v1/airports')

if __name__ == "__main__":
    try:
        app.run()
    except KeyboardInterrupt:
        pass
