from navigator.commands import BaseCommand
from navigator.commands.exceptions import CommandError
from navigator.conf import asyncpg_url


class ProgramCommand(BaseCommand):
    help = "Program Creation and maintenance for Navigator."
    _version: str = '0.1'

    def configure(self):
        super(ProgramCommand, self).configure()
        self.add_argument("--program", type=str)

    async def creation(self, options, **kwargs):
        await self.create(options, **kwargs)
        return await self.task_infra(options, **kwargs)

    async def create(self, options, **kwargs):
        """Command infraestructure uses pyDoc as helper for Command."""
        args = {
            "program": options.program,
            "db_user": "troc_pgdata"
        }
        print('ARGS ', args)
        qry = await self.tplparser.render(
            filename='programs/schema.sql',
            params=args
        )
        tables = await self.tplparser.render(
            filename='programs/basic_tables.sql',
            params=args
        )
        slugs = await self.tplparser.render(
            filename='programs/basic_slugs.sql',
            params=args
        )
        async with await self.db_connection(dsn=asyncpg_url).connection() as conn:
            self.write(
                "* First Step: Creation of Empty Schema"
            )
            _, error = await conn.execute(qry)
            if error:
                raise CommandError(str(error))
            self.write(
                "* Second Step: Creation of Basic Tables:"
            )
            _, error = await conn.execute(tables)
            print('ERR > ', error)
            if error:
                raise CommandError(str(error))
            self.write(
                "* Third Step: Creation of Basic Slugs:"
            )
            _, error = await conn.execute(slugs)
            print('ERR > ', error)
            if error:
                raise CommandError(str(error))
        # Create Default Task Path and File Path
        return f'Program Schema was created => {options.program}'

    async def task_infra(self, options, **kwargs):
        """task_infra.

        Create Task infraestructure (Task table, views, etc)
        """
        args = {
            "program": options.program,
            "db_user": "troc_pgdata"
        }
        tasks = await self.tplparser.render(
            filename='programs/tasks.sql',
            params=args
        )
        async with await self.db_connection(dsn=asyncpg_url).connection() as conn:
            self.write(
                "* Step: Creation Task Table"
            )
            _, error = await conn.execute(tasks)
            print('Error?: ', error)
            if error:
                raise CommandError(str(error))
        return f'Task Table for {options.program} was created.'
