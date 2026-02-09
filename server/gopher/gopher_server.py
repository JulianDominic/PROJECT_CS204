import socket
import threading
import os
import argparse

DEFAULT_HOST = '0.0.0.0'
DEFAULT_PORT = 70
CONTENT_DIR = "../../data/content"

class GopherHandler:
    def __init__(self, request, client_address, root_dir):
        self.request = request
        self.client_address = client_address
        self.root_dir = os.path.abspath(root_dir)

    def handle(self):
        try:
            selector = self.request.recv(1024).strip().decode('utf-8', errors='ignore')
            print(f"[{self.client_address}] Request: {selector}")
            
            if not selector:
                # Default to index
                self.send_index(self.root_dir)
                return

            # Sanitize path
            path = os.path.normpath(os.path.join(self.root_dir, selector))
            if not path.startswith(self.root_dir):
                self.send_error("Access Denied")
                return

            if os.path.isdir(path):
                self.send_index(path)
            elif os.path.isfile(path):
                self.send_file(path)
            else:
                self.send_error("File Not Found")
        
        except Exception as e:
            print(f"Error handling request: {e}")
        finally:
            self.request.close()

    def send_index(self, directory):
        response = ""
        try:
            items = os.listdir(directory)
            for item in items:
                path = os.path.join(directory, item)
                if os.path.isdir(path):
                    response += f"1{item}\t{item}\tlocalhost\t70\r\n"
                else:
                    response += f"0{item}\t{item}\tlocalhost\t70\r\n"
        except Exception as e:
            self.send_error(f"Error listing directory: {e}")
            return

        response += ".\r\n"
        self.request.sendall(response.encode('utf-8'))

    def send_file(self, filepath):
        try:
            with open(filepath, 'rb') as f:
                while True:
                    data = f.read(4096)
                    if not data:
                        break
                    self.request.sendall(data)
            # Gopher file transfer ends when connection closes, but technically ends with . if text?
            # Binary files just stream until close.
        except Exception as e:
            self.send_error(f"Error reading file: {e}")

    def send_error(self, message):
        response = f"3{message}\t\terror.host\t1\r\n"
        self.request.sendall(response.encode('utf-8'))

def run_server(host=DEFAULT_HOST, port=DEFAULT_PORT, content_dir=CONTENT_DIR):
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((host, port))
    server_socket.listen(5)
    print(f"Gopher server listening on {host}:{port} serving {content_dir}")

    try:
        while True:
            client_sock, client_addr = server_socket.accept()
            handler = GopherHandler(client_sock, client_addr, content_dir)
            threading.Thread(target=handler.handle).start()
    except KeyboardInterrupt:
        print("\nServer stopping...")
    finally:
        server_socket.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple Gopher Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind to")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on")
    parser.add_argument("--dir", default=CONTENT_DIR, help="Content directory")
    args = parser.parse_args()
    
    run_server(args.host, args.port, args.dir)
