#!/usr/bin/env bash
set -e

docker build -t cs204-bench .
mkdir -p results

if [ "$1" = "test" ]; then
    shift
    # Run test suite directly
    docker run --rm -v "$(pwd)/results:/app/results" cs204-bench \
        python run_test_suite.py "$@"
else
    # Launch interactive dashboard
    echo "Starting dashboard at http://localhost:8501"
    docker run --rm -p 8501:8501 -v "$(pwd)/results:/app/results" cs204-bench
fi
