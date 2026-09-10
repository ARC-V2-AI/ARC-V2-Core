import asyncio
import json

from arc.pulse.pulse import CONTROL_SOCKET


async def request_status():
    reader, writer = await asyncio.open_unix_connection(str(CONTROL_SOCKET))

    try:
        writer.write(b'{"command":"status"}\n')
        await writer.drain()

        data = await reader.readline()

        return json.loads(data)

    finally:
        writer.close()
        await writer.wait_closed()
