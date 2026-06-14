#!/bin/bash

# Function to check if a service is ready
wait_for_service() {
    local host=$1
    local port=$2
    local service=$3
    
    echo "Waiting for $service to be ready..."
    while ! timeout 1 bash -c ">/dev/tcp/$host/$port" 2>/dev/null; do
        sleep 1
    done
    echo "$service is ready!"
}

# Function to check if port is in use
check_port() {
    local port=$1
    if lsof -i :$port > /dev/null 2>&1; then
        echo "Port $port is in use. Attempting to free it..."
        lsof -i :$port | grep LISTEN | awk '{print $2}' | xargs -r kill -9
        sleep 2
    fi
}

# Stop any existing uvicorn processes and check port
echo "Cleaning up existing processes..."
pkill -f uvicorn
pkill -f process_card_transactions.py
check_port 3001

# Start Docker containers if they're not running
echo "Starting Docker containers..."
docker-compose up -d

# Wait for services to be ready
wait_for_service localhost 27017 "MongoDB"
wait_for_service localhost 3306 "MySQL"
wait_for_service localhost 6379 "Redis"

# Start the application
echo "Starting application..."
source venv/bin/activate
export PYTHONPATH=$PYTHONPATH:$(pwd)
export WORKER_ID=0

# Start process_card_transactions.py in the background
echo "Starting process_card_transactions.py..."
python process_card_transactions.py &

# Start the FastAPI application
echo "Starting FastAPI application..."
uvicorn app:app --host 0.0.0.0 --port 3001 --workers 1

# Wait for both processes
wait