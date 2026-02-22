import subprocess
import time
import os
import signal
import sys
import pandas as pd
import matplotlib.pyplot as plt

# Configuration
GOPHER_PORT = 7070
HTTP_PORT = 8080
GOPHER_PROXY_PORT = 9070
HTTP_PROXY_PORT = 9080

SCENARIOS = [
    {"name": "Baseline", "latency": 0, "loss": 0},
    {"name": "High_Latency", "latency": 100, "loss": 0},
    {"name": "Packet_Loss", "latency": 0, "loss": 5},
    {"name": "Mixed", "latency": 50, "loss": 2}
]

FILES = ["1kb.txt", "100kb.txt"]
RUNS_PER_TEST = 5

RESULTS_DIR = "results"

def start_process(cmd):
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def run_suite():
    if not os.path.exists(RESULTS_DIR):
        os.makedirs(RESULTS_DIR)

    print("Starting Test Suite...")
    
    # Start Servers
    print("Starting Servers...")
    # Explicitly pass content directory
    content_dir = os.path.abspath("data/content")
    
    gopher_server = start_process([
        sys.executable, "server/gopher/gopher_server.py", 
        "--port", str(GOPHER_PORT),
        "--dir", content_dir
    ])
    
    http_server = start_process([
        sys.executable, "server/http/http_server.py", 
        "--port", str(HTTP_PORT),
        "--dir", content_dir
    ])
    
    time.sleep(2) # Wait for startup
    
    try:
        for scenario in SCENARIOS:
            print(f"\n--- Scenario: {scenario['name']} ---")
            
            # Start Proxies
            gopher_proxy = start_process([
                sys.executable, "server/proxy.py", 
                "--target_host", "localhost", "--target_port", str(GOPHER_PORT),
                "--listen_port", str(GOPHER_PROXY_PORT),
                "--latency", str(scenario['latency']), "--loss", str(scenario['loss'])
            ])
            
            http_proxy = start_process([
                sys.executable, "server/proxy.py", 
                "--target_host", "localhost", "--target_port", str(HTTP_PORT),
                "--listen_port", str(HTTP_PROXY_PORT),
                "--latency", str(scenario['latency']), "--loss", str(scenario['loss'])
            ])
            
            time.sleep(1) # Wait for proxy startup
            
            # Create scenario-specific results file
            scenario_results_file = os.path.join(RESULTS_DIR, f"results_{scenario['name']}.csv")
            
            for file in FILES:
                print(f"Testing {file}...")
                
                # Test Gopher
                subprocess.run([
                    sys.executable, "client/benchmark.py",
                    "--host", "localhost", "--port", str(GOPHER_PROXY_PORT),
                    "--protocol", "gopher", "--file", file,
                    "--runs", str(RUNS_PER_TEST), "--output", scenario_results_file
                ])
                
                # Test HTTP
                subprocess.run([
                    sys.executable, "client/benchmark.py",
                    "--host", "localhost", "--port", str(HTTP_PROXY_PORT),
                    "--protocol", "http", "--file", file,
                    "--runs", str(RUNS_PER_TEST), "--output", scenario_results_file
                ])
            
            # Kill Proxies
            gopher_proxy.terminate()
            http_proxy.terminate()
            gopher_proxy.wait()
            http_proxy.wait()
            time.sleep(1)  # Allow ports to fully release
            gopher_proxy.wait()  # Add this to wait for process exit
            http_proxy.wait()    # Add this to wait for process exit
            
    finally:
        print("\nStopping Servers...")
        gopher_server.terminate()
        http_server.terminate()
        
    print("Test Suite Completed.")
    analyze_results()

def analyze_results():
    print("Analyzing results...")
    
    all_results = []
    
    for scenario in SCENARIOS:
         file_path = os.path.join(RESULTS_DIR, f"results_{scenario['name']}.csv")
         if os.path.exists(file_path):
             df = pd.read_csv(file_path)
             df['scenario'] = scenario['name']
             all_results.append(df)
    
    if not all_results:
        print("No results found.")
        return

    combined_df = pd.concat(all_results)
    
    summary_file = os.path.join(RESULTS_DIR, "summary_statistics.csv")
    summary = combined_df.groupby(['scenario', 'protocol', 'file'])[['ttfb', 'total_time']].mean()
    summary.to_csv(summary_file)
    print(f"\nSummary Statistics saved to {summary_file}")
    
    # Generate Charts per Scenario
    for scenario in SCENARIOS:
        scenario_name = scenario['name']
        data = combined_df[combined_df['scenario'] == scenario_name]
        
        if data.empty:
            continue

        plt.figure(figsize=(10, 6))
        for (protocol, file), group in data.groupby(['protocol', 'file']):
            plt.plot(group['ttfb'].reset_index(drop=True), label=f"{protocol} - {file}")
        
        plt.title(f"TTFB Comparison - {scenario_name}")
        plt.xlabel("Test Run")
        plt.ylabel("Time (ms)")
        plt.legend()
        plt.savefig(os.path.join(RESULTS_DIR, f"ttfb_{scenario_name}.png"))
        plt.close()

    print(f"Charts saved to {RESULTS_DIR}/")

if __name__ == "__main__":
    run_suite()
