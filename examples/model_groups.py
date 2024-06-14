import asyncio
from datetime import datetime
from asyncdb.models import Model, Column
from asyncdb import AsyncPool
from navigator_auth import AuthHandler
from navigator import Application
from navigator.views import ModelView


class Group(Model):
    group_id: int = Column(
        required=False, primary_key=True, db_default='auto', repr=False
    )
    group_name: str = Column(required=True)
    client_id: int = Column(
        required=False, fk="client_id|client", api="clients"
    )
    is_active: bool = Column(required=True, default=True)
    created_at: datetime = Column(
        required=False, default=datetime.now(), repr=False
    )
    updated_at: datetime = Column(
        required=False, default=datetime.now(), repr=False
    )
    created_by: str = Column(required=False, repr=False)

    class Meta:
        name = "groups"
        schema = "auth"
        description = 'Group Management'
        strict = True


class GroupManager(ModelView):
    model: Model = Group
    pk: str = 'group_id'

    async def _set_created_by(self, value, column, **kwargs):
        return await self.get_userid(session=self._session)

    def required_by_put(self):
        return ['group_name']

    async def on_startup(self, *args, **kwargs):
        print(args, kwargs)
        print('THIS CODE RUN ON STARTUP')


async def start_example(db):
    """
    Start Application DB
    """
    await db.connect()

if __name__ == "__main__":
    params = {
        "user": "troc_pgdata",
        "password": "12345678",
        "host": "127.0.0.1",
        "port": "5432",
        "database": "navigator",
        "DEBUG": True,
    }
    kwargs = {
        "server_settings": {
            'client_min_messages': 'notice',
            'max_parallel_workers': '24',
            'tcp_keepalives_idle': '30'
        }
    }
    try:
        ## Create Application
        app = Application()
        loop = app.event_loop()
        pool = AsyncPool("pg", params=params, loop=loop, **kwargs)
        app['database'] = pool
        loop.run_until_complete(
            start_example(pool)
        )
        session = AuthHandler()
        session.setup(app)
        ## two required handlers for a ModelView.
        GroupManager.configure(app, '/api/v1/groups')
        print('=== START APP === ')
        app.run()
    except KeyboardInterrupt:
        print(' == CLOSING APP == ')
