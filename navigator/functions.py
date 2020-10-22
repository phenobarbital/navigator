import asyncio
from typing import List


async def run_cmd(cmd: List) -> str:
    print(f'Executing: {" ".join(cmd)}')
    process = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE)
    out, error = await process.communicate()
    if error:
        raise Exception(error)
    return out.decode("utf8")


def escapeString(value):
    v = value if value != "None" else ""
    v = str(v).replace("'", "''")
    v = "'{}'".format(v) if type(v) == str else v
    return v
