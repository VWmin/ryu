import asyncio

from pyof.utils import unpack

from ryu.ofproto import ofproto_common, ofproto_parser


async def handle_client(mn_reader, mn_writer):
    try:
        ryu_reader, ryu_writer = await asyncio.open_connection('localhost', 6633)

        async def relay(r, rw, direction):
            buf = b''
            min_read_len = remaining_read_len = ofproto_common.OFP_HEADER_SIZE
            while True:
                try:
                    read_len = min_read_len
                    if remaining_read_len > min_read_len:
                        read_len = remaining_read_len
                    ret = await r.read(read_len)
                except (EOFError, IOError):
                    break

                if not ret:
                    break

                buf += ret
                buf_len = len(buf)
                while buf_len >= min_read_len:
                    (version, msg_type, msg_len, xid) = ofproto_parser.header(buf)
                    # print(version, msg_type, msg_len, xid)
                    if msg_len < min_read_len:
                        msg_len = min_read_len
                    if buf_len < msg_len:
                        remaining_read_len = (msg_len - buf_len)
                        break

                    msg = unpack(buf[:msg_len])
                    if msg:
                        print(f"{direction}: {msg}")
                        rw.write(buf[:msg_len])
                        await rw.drain()

                    buf = buf[msg_len:]
                    buf_len = len(buf)
                    remaining_read_len = min_read_len

        await asyncio.gather(
            relay(mn_reader, ryu_writer, "mn -> ryu"),
            relay(ryu_reader, mn_writer, "ryu -> mn")
        )

    finally:
        mn_writer.close()


async def main():
    server = await asyncio.start_server(handle_client, '127.0.0.1', 8888)
    async with server:
        await server.serve_forever()


asyncio.run(main())
