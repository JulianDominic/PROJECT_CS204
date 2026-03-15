"""
Modern Gopher Server — Persistent TCP Connections

This extends the classic Gopher protocol (RFC 1436) with persistent connections,
similar to how HTTP/1.1's keep-alive improved over HTTP/1.0.

┌──────────────────────────────────────────────────────────────────────┐
│  Classic (Original) Gopher          Modern Gopher                   │
│  ─────────────────────────          ──────────────────              │
│  1 TCP connection → 1 request       1 TCP connection → N requests   │
│  Connection closed after response   Connection stays open           │
│                                                                      │
│  Problem: TCP Slow Start on         Advantage: TCP window grows,    │
│  every single request               amortises handshake cost        │
└──────────────────────────────────────────────────────────────────────┘

Protocol framing (extension over RFC 1436):
  Request:   <selector>\\r\\n
  Response:  <content-length>\\r\\n<raw bytes of exactly that length>
  Close:     QUIT\\r\\n  (or client closes the socket)

The length prefix lets the client know when a response ends WITHOUT
closing the connection — the key enabler for persistence.
"""

import socket
import threading
import os
import argparse

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 7071
CONTENT_DIR = "../../data/content"


class ModernGopherHandler:
    """Handle a single persistent client connection."""

    def __init__(self, client_socket, client_address, root_dir, server_port):
        self.socket = client_socket
        self.address = client_address
        self.root_dir = os.path.abspath(root_dir)
        self.server_port = server_port
        self.buffer = b""

    def handle(self):
        """Read requests in a loop until the client disconnects or sends QUIT."""
        try:
            self.socket.settimeout(30.0)  # Idle timeout
            while True:
                line = self._read_line()
                if line is None:
                    break  # Client disconnected

                selector = line.strip()

                if selector.upper() == "QUIT":
                    break

                if not selector:
                    self._send_index(self.root_dir)
                    continue

                # Prevent directory traversal
                path = os.path.normpath(os.path.join(self.root_dir, selector))
                if not path.startswith(self.root_dir):
                    self._send_error("Access Denied")
                    continue

                if os.path.isdir(path):
                    self._send_index(path)
                elif os.path.isfile(path):
                    self._send_file(path)
                else:
                    self._send_error("File Not Found")

        except socket.timeout:
            pass  # Idle timeout — clean close
        except Exception as e:
            print(f"[{self.address}] Error: {e}")
        finally:
            self.socket.close()

    # ── Buffered line reader ─────────────────────────────────────────

    def _read_line(self):
        """Read bytes until \\r\\n, using an internal buffer."""
        while b"\r\n" not in self.buffer:
            try:
                chunk = self.socket.recv(4096)
                if not chunk:
                    return None
                self.buffer += chunk
            except (ConnectionResetError, OSError):
                return None

        line, self.buffer = self.buffer.split(b"\r\n", 1)
        return line.decode("utf-8", errors="ignore")

    # ── Length-prefixed response helpers ──────────────────────────────

    def _send_response(self, data):
        """Send: <content-length>\\r\\n<raw bytes>"""
        if isinstance(data, str):
            data = data.encode("utf-8")
        header = f"{len(data)}\r\n".encode("utf-8")
        self.socket.sendall(header + data)

    def _send_file(self, filepath):
        try:
            filesize = os.path.getsize(filepath)
            header = f"{filesize}\r\n".encode("utf-8")
            self.socket.sendall(header)
            with open(filepath, "rb") as f:
                while True:
                    chunk = f.read(4096)
                    if not chunk:
                        break
                    self.socket.sendall(chunk)
        except Exception as e:
            self._send_error(f"Error reading file: {e}")

    def _send_index(self, directory):
        response = ""
        try:
            for item in sorted(os.listdir(directory)):
                path = os.path.join(directory, item)
                item_type = "1" if os.path.isdir(path) else "0"
                response += f"{item_type}{item}\t{item}\tlocalhost\t{self.server_port}\r\n"
        except Exception as e:
            self._send_error(f"Error listing directory: {e}")
            return
        response += ".\r\n"
        self._send_response(response)

    def _send_error(self, message):
        response = f"3{message}\t\terror.host\t1\r\n"
        self._send_response(response)


def run_server(host=DEFAULT_HOST, port=DEFAULT_PORT, content_dir=CONTENT_DIR):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"Modern Gopher server on {host}:{port}  (persistent connections)")
    print(f"Serving: {os.path.abspath(content_dir)}")

    try:
        while True:
            client_sock, client_addr = server_socket.accept()
            handler = ModernGopherHandler(client_sock, client_addr, content_dir, port)
            threading.Thread(target=handler.handle, daemon=True).start()
    except KeyboardInterrupt:
        print("\nServer stopping...")
    finally:
        server_socket.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Modern Gopher Server (Persistent TCP Connections)"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--dir", default=CONTENT_DIR)
    args = parser.parse_args()

    run_server(args.host, args.port, args.dir)
