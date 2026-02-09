import socket
import time
import requests
import argparse
import csv
import os
from datetime import datetime

class Benchmark:
    def __init__(self, host, port, protocol, filename, output_file="results.csv"):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.filename = filename
        self.output_file = output_file
        self.results = []

    def run_test(self, runs=10):
        print(f"Running {runs} tests for {self.protocol} on {self.filename}...")
        
        for i in range(runs):
            if self.protocol == 'gopher':
                result = self.measure_gopher()
            elif self.protocol == 'http':
                result = self.measure_http()
            
            if result:
                self.results.append(result)
                print(f"Run {i+1}: TTFB={result['ttfb']:.2f}ms Total={result['total_time']:.2f}ms")
            else:
                print(f"Run {i+1}: Failed")

        self.save_results()

    def measure_gopher(self):
        start_time = time.time()
        ttfb = 0
        total_time = 0
        bytes_received = 0
        
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(10.0) # 10s timeout
            s.connect((self.host, self.port))
            
            # Send selector
            request = f"{self.filename}\r\n"
            s.sendall(request.encode('utf-8'))
            
            # Receive response
            first_chunk = True
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                
                if first_chunk:
                    ttfb = (time.time() - start_time) * 1000
                    first_chunk = False
                
                bytes_received += len(chunk)
            
            total_time = (time.time() - start_time) * 1000
            s.close()
            
            return {
                "timestamp": datetime.now().isoformat(),
                "protocol": "gopher",
                "file": self.filename,
                "ttfb": ttfb,
                "total_time": total_time,
                "bytes": bytes_received,
                "throughput": ((bytes_received * 8) / total_time) if total_time > 0 else 0
            }
            
        except Exception as e:
            print(f"Gopher Error: {e}")
            return None

    def measure_http(self):
        start_time = time.time()
        ttfb = 0
        total_time = 0
        bytes_received = 0
        
        try:
            url = f"http://{self.host}:{self.port}/{self.filename}"
            
            # Use requests but with stream=True to measure TTFB
            with requests.get(url, stream=True, timeout=10.0) as r:
                # Time to headers is roughly TTFB
                ttfb = (time.time() - start_time) * 1000
                
                for chunk in r.iter_content(chunk_size=4096):
                    bytes_received += len(chunk)
            
            total_time = (time.time() - start_time) * 1000
            
            return {
                "timestamp": datetime.now().isoformat(),
                "protocol": "http",
                "file": self.filename,
                "ttfb": ttfb,
                "total_time": total_time,
                "bytes": bytes_received,
                "throughput": ((bytes_received * 8) / total_time) if total_time > 0 else 0
            }
            
        except Exception as e:
            print(f"HTTP Error: {e}")
            return None

    def save_results(self):
        file_exists = os.path.isfile(self.output_file)
        
        with open(self.output_file, 'a', newline='') as f:
            fieldnames = ["timestamp", "protocol", "file", "ttfb", "total_time", "bytes", "throughput"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            if not file_exists:
                writer.writeheader()
                
            for result in self.results:
                writer.writerow(result)
        
        print(f"Results saved to {self.output_file}")
        self.results = [] # Clear after save

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Protocol Benchmark Client")
    parser.add_argument("--host", default="localhost", help="Target host")
    parser.add_argument("--port", type=int, required=True, help="Target port")
    parser.add_argument("--protocol", choices=['gopher', 'http'], required=True, help="Protocol to test")
    parser.add_argument("--file", required=True, help="File to request")
    parser.add_argument("--runs", type=int, default=10, help="Number of runs")
    parser.add_argument("--output", default="results.csv", help="Output file")
    
    args = parser.parse_args()
    
    bench = Benchmark(args.host, args.port, args.protocol, args.file, args.output)
    bench.run_test(args.runs)
