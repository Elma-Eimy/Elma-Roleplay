import asyncio

async def forward(reader, writer):
    try:
        remote_reader, remote_writer = await asyncio.open_connection("127.0.0.1", 8000)
    except Exception:
        writer.close()
        return

    async def pipe(r, w):
        try:
            while not r.at_eof():
                data = await r.read(65536)
                if not data:
                    break
                w.write(data)
                await w.drain()
        except Exception:
            pass
        finally:
            try:
                w.close()
            except Exception:
                pass

    await asyncio.gather(pipe(reader, remote_writer), pipe(remote_reader, writer))

async def main():
    server = await asyncio.start_server(forward, "127.0.0.1", 8080)
    print("TCP Proxy listening on 127.0.0.1:8080 -> 127.0.0.1:8000", flush=True)
    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
