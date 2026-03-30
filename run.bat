@echo off
docker build -t cs204-bench .
if not exist results mkdir results

if "%1"=="test" (
    shift
    docker run --rm -v "%cd%/results:/app/results" cs204-bench python run_test_suite.py %*
) else (
    echo Starting dashboard at http://localhost:8501
    docker run --rm -p 8501:8501 -v "%cd%/results:/app/results" cs204-bench
)
