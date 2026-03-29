"""
UDP Network Condition Proxy - for QUIC / HTTP/3 testing.

Uses asyncio datagram transports instead of per-packet timer threads. This keeps
delayed QUIC traffic ordered and stable enough for latency/loss benchmarking.
"""

import argparse
import asyncio
import random
import socket


class UpstreamProtocol(asyncio.DatagramProtocol):
    def __init__(self, proxy, client_addr):
        self.proxy = proxy
        self.client_addr = client_addr
        self.transport = None

    def connection_made(self, transport):
        self.transport = transport
        self.proxy.register_upstream(self.client_addr, transport)

    def datagram_received(self, data, addr):
        self.proxy.handle_server_datagram(self.client_addr, data)

    def connection_lost(self, exc):
        self.proxy.unregister_upstream(self.client_addr, self.transport)


class ProxyProtocol(asyncio.DatagramProtocol):
    def __init__(self, proxy):
        self.proxy = proxy

    def connection_made(self, transport):
        self.proxy.listen_transport = transport

    def datagram_received(self, data, addr):
        self.proxy.handle_client_datagram(addr, data)


class UDPProxy:
    def __init__(
        self,
        target_host,
        target_port,
        listen_host="0.0.0.0",
        listen_port=9433,
        latency=0,
        loss=0,
        bandwidth=0,
        warmup_packets=8,
    ):
        self.target = self._resolve_target(target_host, target_port)
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.latency = latency / 1000.0
        self.loss = loss / 100.0
        self.bandwidth = bandwidth  # bytes per second (0 = unlimited)
        self.warmup_packets = max(0, warmup_packets)

        self.loop = None
        self.listen_transport = None
        self.upstreams = {}
        self.packet_counts = {}
        self.send_order = 0

    def _resolve_target(self, host, port):
        infos = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
        if not infos:
            raise OSError(f"Could not resolve UDP target {host}:{port}")
        return infos[0][4]

    def _count_packet(self, client_addr):
        count = self.packet_counts.get(client_addr, 0) + 1
        self.packet_counts[client_addr] = count
        return count

    def _should_drop(self, client_addr):
        count = self._count_packet(client_addr)
        if count <= self.warmup_packets:
            return False
        return self.loss > 0 and random.random() < self.loss

    def _schedule_send(self, transport, data, addr):
        delay = self.latency if self.latency > 0 else 0
        if self.bandwidth > 0:
            delay += len(data) / self.bandwidth
        self.send_order += 1
        order = self.send_order
        self.loop.call_later(delay, self._send_now, transport, data, addr, order)

    @staticmethod
    def _send_now(transport, data, addr, order):
        if transport.is_closing():
            return
        if addr is None:
            transport.sendto(data)
        else:
            transport.sendto(data, addr)

    def register_upstream(self, client_addr, transport):
        self.upstreams[client_addr] = transport

    def unregister_upstream(self, client_addr, transport):
        current = self.upstreams.get(client_addr)
        if current is transport:
            self.upstreams.pop(client_addr, None)
            self.packet_counts.pop(client_addr, None)

    def handle_client_datagram(self, client_addr, data):
        if self._should_drop(client_addr):
            return

        upstream = self.upstreams.get(client_addr)
        if upstream is None:
            self.loop.create_task(self._create_upstream_and_forward(client_addr, data))
            return

        self._schedule_send(upstream, data, None)

    def handle_server_datagram(self, client_addr, data):
        if self._should_drop(client_addr):
            return
        if self.listen_transport is None or self.listen_transport.is_closing():
            return
        self._schedule_send(self.listen_transport, data, client_addr)

    async def _create_upstream_and_forward(self, client_addr, initial_data):
        if client_addr in self.upstreams:
            upstream = self.upstreams[client_addr]
            self._schedule_send(upstream, initial_data, None)
            return

        transport, _ = await self.loop.create_datagram_endpoint(
            lambda: UpstreamProtocol(self, client_addr),
            remote_addr=self.target,
            family=socket.AF_INET,
        )
        self._schedule_send(transport, initial_data, None)

    async def run(self):
        self.loop = asyncio.get_running_loop()
        transport, _ = await self.loop.create_datagram_endpoint(
            lambda: ProxyProtocol(self),
            local_addr=(self.listen_host, self.listen_port),
            family=socket.AF_INET,
        )
        self.listen_transport = transport

        print(f"UDP Proxy on :{self.listen_port} -> {self.target[0]}:{self.target[1]}")
        print(f"Conditions: latency={self.latency*1000:.0f}ms  loss={self.loss*100:.0f}%  bw={self.bandwidth}B/s")

        try:
            await asyncio.Future()
        finally:
            transport.close()
            for upstream in list(self.upstreams.values()):
                upstream.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP Network Condition Proxy")
    parser.add_argument("--target_host", required=True)
    parser.add_argument("--target_port", required=True, type=int)
    parser.add_argument("--listen_port", type=int, default=9433)
    parser.add_argument("--latency", type=float, default=0, help="Latency in ms")
    parser.add_argument("--loss", type=float, default=0, help="Packet loss %%")
    parser.add_argument("--bandwidth", type=int, default=0, help="Bandwidth in bytes/sec (0=unlimited)")
    parser.add_argument(
        "--warmup_packets",
        type=int,
        default=8,
        help="Do not drop the first N client packets to avoid random QUIC handshake failure",
    )
    args = parser.parse_args()

    proxy = UDPProxy(
        args.target_host,
        args.target_port,
        listen_port=args.listen_port,
        latency=args.latency,
        loss=args.loss,
        bandwidth=args.bandwidth,
        warmup_packets=args.warmup_packets,
    )

    try:
        asyncio.run(proxy.run())
    except KeyboardInterrupt:
        print("\nStopping UDP proxy...")
