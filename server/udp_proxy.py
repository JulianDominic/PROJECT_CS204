"""
UDP Network Condition Proxy - for QUIC / HTTP/3 testing.

Works alongside proxy.py (TCP) to simulate network impairments on UDP traffic.
QUIC uses UDP, so the existing TCP proxy cannot be used for HTTP/3 benchmarks.
"""

import argparse
import random
import socket
import threading


class UDPProxy:
    def __init__(
        self,
        target_host,
        target_port,
        listen_host="0.0.0.0",
        listen_port=9433,
        latency=0,
        loss=0,
    ):
        self.target = self._resolve_target(target_host, target_port)
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.latency = latency / 1000.0
        self.loss = loss / 100.0
        self.running = True
        self.client_map = {}
        self.lock = threading.Lock()

    def _resolve_target(self, host, port):
        infos = socket.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
        if not infos:
            raise OSError(f"Could not resolve UDP target {host}:{port}")
        return infos[0][4]

    def _should_drop(self):
        return self.loss > 0 and random.random() < self.loss

    def _delayed_send(self, sock, data, addr):
        if self.latency > 0:
            jitter = self.latency * 0.1
            delay = max(0, self.latency + random.uniform(-jitter, jitter))
            timer = threading.Timer(delay, self._do_send, args=(sock, data, addr))
            timer.daemon = True
            timer.start()
        else:
            self._do_send(sock, data, addr)

    def _do_send(self, sock, data, addr):
        try:
            sock.sendto(data, addr)
        except OSError:
            pass

    def _relay_responses(self, relay_sock, listen_sock, client_addr):
        relay_sock.settimeout(60.0)
        try:
            while self.running:
                try:
                    data, _ = relay_sock.recvfrom(65535)
                except socket.timeout:
                    break

                if self._should_drop():
                    continue

                self._delayed_send(listen_sock, data, client_addr)
        except Exception:
            pass
        finally:
            relay_sock.close()
            with self.lock:
                self.client_map.pop(client_addr, None)

    def start(self):
        listen_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listen_sock.bind((self.listen_host, self.listen_port))

        print(f"UDP Proxy on :{self.listen_port} -> {self.target[0]}:{self.target[1]}")
        print(f"Conditions: latency={self.latency*1000:.0f}ms  loss={self.loss*100:.0f}%")

        try:
            while self.running:
                data, client_addr = listen_sock.recvfrom(65535)

                if self._should_drop():
                    continue

                with self.lock:
                    if client_addr not in self.client_map:
                        relay_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        self.client_map[client_addr] = relay_sock
                        threading.Thread(
                            target=self._relay_responses,
                            args=(relay_sock, listen_sock, client_addr),
                            daemon=True,
                        ).start()
                    relay_sock = self.client_map[client_addr]

                self._delayed_send(relay_sock, data, self.target)
        except KeyboardInterrupt:
            print("\nStopping UDP proxy...")
        finally:
            self.running = False
            listen_sock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UDP Network Condition Proxy")
    parser.add_argument("--target_host", required=True)
    parser.add_argument("--target_port", required=True, type=int)
    parser.add_argument("--listen_port", type=int, default=9433)
    parser.add_argument("--latency", type=float, default=0, help="Latency in ms")
    parser.add_argument("--loss", type=float, default=0, help="Packet loss %%")
    args = parser.parse_args()

    proxy = UDPProxy(
        args.target_host,
        args.target_port,
        listen_port=args.listen_port,
        latency=args.latency,
        loss=args.loss,
    )
    proxy.start()
