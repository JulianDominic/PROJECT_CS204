from flask import Flask, send_from_directory
import os
import argparse

app = Flask(__name__)
CONTENT_DIR = "../../data/content"

@app.route('/')
def index():
    try:
        files = os.listdir(app.config['CONTENT_DIR'])
        html = "<html><body><h1>Files</h1><ul>"
        for f in files:
            html += f'<li><a href="/{f}">{f}</a></li>'
        html += "</ul></body></html>"
        return html
    except Exception as e:
        return f"Error: {e}", 500

@app.route('/<path:filename>')
def serve_file(filename):
    return send_from_directory(app.config['CONTENT_DIR'], filename)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Simple HTTP Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--dir", default=CONTENT_DIR, help="Content directory")
    args = parser.parse_args()

    app.config['CONTENT_DIR'] = os.path.abspath(args.dir)
    print(f"HTTP server listening on {args.host}:{args.port} serving {app.config['CONTENT_DIR']}")
    app.run(host=args.host, port=args.port)
