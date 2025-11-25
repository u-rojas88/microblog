# Service Registry

A service registry that maintains service instances in memory using Python dictionaries with thread-safe access via `asyncio.Lock`.

## Features

✅ **In-memory storage** using Python dictionaries  
✅ **Thread-safe** with `asyncio.Lock` for concurrent access  
✅ **Service registration** on startup  
✅ **Service discovery** - query instances by service name  
✅ **Heartbeat mechanism** - automatic cleanup of stale instances  
✅ **Multithreaded/async-safe** - handles concurrent requests  

## Architecture

### Data Structure

The registry uses a nested dictionary structure:
```python
{
    "users": [
        {
            "instance_id": "uuid-here",
            "service_name": "users",
            "base_url": "http://localhost:8000",
            "registered_at": 1234567890.0,
            "last_heartbeat": 1234567890.0,
            ...
        }
    ],
    "timelines": [...],
    ...
}
```

### Locking

- Uses `asyncio.Lock` for thread-safe access
- All registry operations (read/write) are protected by the lock
- FastAPI's async nature ensures non-blocking concurrent requests

## API Endpoints

### Register Service
```bash
POST /register
{
    "service_name": "users",
    "base_url": "http://localhost:8000"
}
```

Returns:
```json
{
    "instance_id": "uuid-here",
    "service_name": "users",
    "base_url": "http://localhost:8000",
    "registered_at": "2024-01-15T10:30:00Z",
    "last_heartbeat": "2024-01-15T10:30:00Z"
}
```

### Send Heartbeat
```bash
POST /heartbeat/{instance_id}
```

### Deregister Service
```bash
DELETE /deregister/{instance_id}
```

### Get Service Instances
```bash
GET /services/{service_name}
```

Returns:
```json
{
    "service_name": "users",
    "instances": [
        {
            "instance_id": "uuid-1",
            "service_name": "users",
            "base_url": "http://localhost:8000",
            "registered_at": "2024-01-15T10:30:00Z",
            "last_heartbeat": "2024-01-15T10:30:00Z"
        }
    ],
    "count": 1
}
```

### List All Services
```bash
GET /services
```

### Get Registry Status
```bash
GET /status
```

## Usage in Services

### Option 1: Using the Client Helper

```python
from registry_service.client import register_service, deregister_service

@app.on_event("startup")
async def startup():
    import os
    port = os.getenv("PORT", "8000")
    base_url = f"http://localhost:{port}"
    await register_service("users", base_url)

@app.on_event("shutdown")
async def shutdown():
    await deregister_service()
```

### Option 2: Manual Registration

```python
import httpx
import os

REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:8006")

@app.on_event("startup")
async def startup():
    port = os.getenv("PORT", "8000")
    base_url = f"http://localhost:{port}"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{REGISTRY_URL}/register",
            json={
                "service_name": "users",
                "base_url": base_url,
            }
        )
        instance_id = response.json()["instance_id"]
        # Store instance_id for heartbeats/deregistration
```

## How It Works

1. **On Startup**: Service calls `POST /register` with service name and base URL
2. **Heartbeats**: Service periodically calls `POST /heartbeat/{instance_id}` (every 10-15 seconds)
3. **Cleanup**: Background task removes instances that haven't sent a heartbeat in 30 seconds
4. **On Shutdown**: Service calls `DELETE /deregister/{instance_id}`

## Thread Safety

- All operations use `async with _registry_lock:` to ensure thread-safe access
- Multiple concurrent requests are handled safely
- Read operations are also locked to prevent race conditions during cleanup

## Configuration

Environment variables:
- `REGISTRY_URL`: URL of the registry service (default: `http://localhost:8006`)
- `HEARTBEAT_TIMEOUT`: Seconds before instance expires (default: 30)
- `CLEANUP_INTERVAL`: Seconds between cleanup runs (default: 10)

