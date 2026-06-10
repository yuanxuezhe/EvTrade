import asyncio
from rpc.client import close_rpc_client, RPClient, RABBITMQ_URL

async def test():
    await close_rpc_client()

    client = RPClient(RABBITMQ_URL)
    await client.connect()
    print('Connected')

    pkt = await client.call("qry_pos")
    print('Got response!')
    print('RS count:', pkt.result_set_count())
    print('Row count:', pkt.row_count())
    print('Headers:', pkt.get_headers())

loop = asyncio.get_event_loop()
loop.run_until_complete(test())