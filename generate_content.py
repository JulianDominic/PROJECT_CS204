"""
Generate test content for protocol benchmarking.

Creates:
  - Standard files (1KB .. 5MB) for single-file / throughput tests
  - 20 × 1KB small files for the multi-object (waterfall) test
  - Gopher index (gophermap)
"""

import os
import random
import string

CONTENT_DIR = "data/content"

# Standard test files
SIZES = {
    "1kb.txt":  1024,
    "10kb.txt": 10 * 1024,
    "100kb.txt": 100 * 1024,
    "1mb.txt":  1024 * 1024,
    "5mb.txt":  5 * 1024 * 1024,
}

# Multi-object test: 20 small files (simulates "page with 20 images")
NUM_SMALL_FILES = 20
SMALL_FILE_SIZE = 1024  # 1 KB each


def generate_file(filepath, size):
    with open(filepath, "w") as f:
        content = "".join(random.choices(string.ascii_letters + string.digits, k=size))
        f.write(content)
    print(f"  {os.path.basename(filepath):20s} ({size:>10,} bytes)")


def main():
    os.makedirs(CONTENT_DIR, exist_ok=True)

    print("Generating test content...\n")

    # ── Standard files ────────────────────────────────────────────────
    print("Standard test files:")
    for name, size in SIZES.items():
        generate_file(os.path.join(CONTENT_DIR, name), size)

    # ── Small files for multi-object (waterfall) test ─────────────────
    print(f"\nMulti-object test files ({NUM_SMALL_FILES} x {SMALL_FILE_SIZE} B):")
    for i in range(NUM_SMALL_FILES):
        name = f"small_{i:02d}.txt"
        generate_file(os.path.join(CONTENT_DIR, name), SMALL_FILE_SIZE)

    # ── Gopher index (gophermap) ──────────────────────────────────────
    all_files = list(SIZES.keys()) + [f"small_{i:02d}.txt" for i in range(NUM_SMALL_FILES)]
    gophermap = "\r\n".join(
        f"0{name}\t{name}\tlocalhost\t70" for name in sorted(all_files)
    ) + "\r\n"

    with open(os.path.join(CONTENT_DIR, "gophermap"), "w") as f:
        f.write(gophermap)
    print("\n  gophermap (index)")

    print("\nDone!")


if __name__ == "__main__":
    main()
