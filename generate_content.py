import os
import random
import string

CONTENT_DIR = "data/content"
SIZES = {
    "1kb.txt": 1024,
    "10kb.txt": 10 * 1024,
    "100kb.txt": 100 * 1024,
    "1mb.txt": 1024 * 1024,
    "5mb.txt": 5 * 1024 * 1024
}

def generate_file(filename, size):
    path = os.path.join(CONTENT_DIR, filename)
    with open(path, 'w') as f:
        # Generate random content
        content = ''.join(random.choices(string.ascii_letters + string.digits, k=size))
        f.write(content)
    print(f"Generated {filename} ({size} bytes)")

def main():
    if not os.path.exists(CONTENT_DIR):
        os.makedirs(CONTENT_DIR)
        
    print("Generating test content...")
    for filename, size in SIZES.items():
        generate_file(filename, size)
    
    # Create an index file for Gopher
    index_content = "\r\n".join([
        f"0{name}\t{name}\tlocalhost\t70" for name in SIZES.keys()
    ]) + "\r\n"
    
    with open(os.path.join(CONTENT_DIR, "gophermap"), 'w') as f:
        f.write(index_content)
    print("Generated gophermap")

if __name__ == "__main__":
    main()
