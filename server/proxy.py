import socket
import threading
import time
import random
import select
import argparse

class NetworkConditioner:
    def __init__(self, target_host, target_port, listen_host='0.0.0.0', listen_port=9999, 
                 latency=0, jitter=0, loss=0, bandwidth=0):
        self.target_host = target_host
        self.target_port = target_port
        self.listen_host = listen_host
        self.listen_port = listen_port
        self.latency = latency / 1000.0  # ms to seconds
        self.jitter = jitter / 1000.0    # ms to seconds
        self.loss = loss / 100.0         # percent to fraction
        self.bandwidth = bandwidth       # bytes per second (0 = unlimited)
        self.running = True

    def handle_client(self, client_socket):
        remote_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            remote_socket.connect((self.target_host, self.target_port))
        except Exception as e:
            print(f"Could not connect to target: {e}")
            client_socket.close()
            return

        # Sockets to read from
        inputs = [client_socket, remote_socket]
        
        try:
            while inputs:
                readable, _, _ = select.select(inputs, [], [])
                for s in readable:
                    other = remote_socket if s is client_socket else client_socket
                    
                    try:
                        data = s.recv(4096)
                    except ConnectionResetError:
                        data = b''

                    if not data:
                        # This side is done sending data (EOF). 
                        # Stop reading from it.
                        inputs.remove(s)
                        try:
                            # Gracefully forward the EOF (FIN packet) to the other side
                            other.shutdown(socket.SHUT_WR)
                        except OSError:
                            pass # The socket might already be fully closed
                        continue
                    
                    # --- Apply Network Conditions ---
                    
                    # 1. Packet Loss
                    if self.loss > 0 and random.random() < self.loss:
                        print(f"Packet loss occurred (simulated delay)")
                        time.sleep(random.uniform(0.2, 1.0))

                    # 2. Latency & Jitter
                    delay = self.latency
                    if self.jitter:
                        delay += random.uniform(-self.jitter, self.jitter)
                    
                    if delay > 0:
                        time.sleep(delay)

                    # 3. Bandwidth Limitation
                    if self.bandwidth > 0:
                        transmit_time = len(data) / self.bandwidth
                        time.sleep(transmit_time)

                    # --- Forward the Data ---
                    try:
                        other.sendall(data)
                    except OSError:
                        # If the other side unexpectedly closed, stop reading
                        if s in inputs:
                            inputs.remove(s)
        
        except Exception as e:
            print(f"Proxy error: {e}")
        finally:
            client_socket.close()
            remote_socket.close()

    def start(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((self.listen_host, self.listen_port))
        server.listen(5)
        print(f"Proxy listening on {self.listen_host}:{self.listen_port} -> {self.target_host}:{self.target_port}")
        print(f"Conditions: Latency={self.latency*1000}ms, Loss={self.loss*100}%, BW={self.bandwidth}B/s")

        try:
            while self.running:
                client, addr = server.accept()
                threading.Thread(target=self.handle_client, args=(client,)).start()
        except KeyboardInterrupt:
            print("Stopping proxy...")
        finally:
            server.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Network Condition Proxy")
    parser.add_argument("--target_host", required=True, help="Target server host")
    parser.add_argument("--target_port", required=True, type=int, help="Target server port")
    parser.add_argument("--listen_port", type=int, default=9999, help="Proxy listen port")
    parser.add_argument("--latency", type=float, default=0, help="Latency in ms")
    parser.add_argument("--loss", type=float, default=0, help="Packet loss %")
    parser.add_argument("--bandwidth", type=int, default=0, help="Bandwidth in bytes/sec (0=unlimited)")
    
    args = parser.parse_args()
    
    proxy = NetworkConditioner(args.target_host, args.target_port, 
                               listen_port=args.listen_port,
                               latency=args.latency, 
                               loss=args.loss,
                               bandwidth=args.bandwidth)
    proxy.start()
