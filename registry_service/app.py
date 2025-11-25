"""
Service Registry

A service registry that maintains service instances in memory using Python dictionaries.
Uses asyncio.Lock for thread-safe concurrent access.

Features:
- Service registration on startup
- Service discovery by name
- Heartbeat mechanism to keep instances alive
- Automatic cleanup of stale instances
- Thread-safe operations using asyncio.Lock
"""

import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, HttpUrl

app = FastAPI(title="Service Registry")

# In-memory storage: service_name -> list of instances
# Structure: {service_name: [{instance_id, base_url, registered_at, last_heartbeat, ...}, ...]}
_registry: Dict[str, List[Dict]] = {}

# Lock for thread-safe access to the registry
_registry_lock = asyncio.Lock()

# Configuration
HEARTBEAT_TIMEOUT = 30  # seconds - instances expire if no heartbeat for this long
CLEANUP_INTERVAL = 10  # seconds - how often to run cleanup


class ServiceRegistration(BaseModel):
    """Request model for service registration."""
    service_name: str
    base_url: HttpUrl


class ServiceInstance(BaseModel):
    """Response model for a service instance."""
    instance_id: str
    service_name: str
    base_url: str
    registered_at: str
    last_heartbeat: str


class ServiceList(BaseModel):
    """Response model for listing service instances."""
    service_name: str
    instances: List[ServiceInstance]
    count: int


class RegistryStatus(BaseModel):
    """Response model for registry status."""
    status: str
    total_services: int
    total_instances: int
    services: Dict[str, int]  # service_name -> instance_count


async def cleanup_stale_instances():
    """Background task to remove instances that haven't sent a heartbeat."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        current_time = time.time()
        
        async with _registry_lock:
            for service_name in list(_registry.keys()):
                instances = _registry[service_name]
                # Filter out stale instances
                active_instances = [
                    inst for inst in instances
                    if current_time - inst["last_heartbeat"] < HEARTBEAT_TIMEOUT
                ]
                
                if active_instances:
                    _registry[service_name] = active_instances
                else:
                    # Remove service if no active instances
                    del _registry[service_name]


@app.on_event("startup")
async def startup():
    """Start background cleanup task."""
    asyncio.create_task(cleanup_stale_instances())


@app.post("/register", response_model=ServiceInstance, status_code=status.HTTP_201_CREATED)
async def register_service(registration: ServiceRegistration):
    """
    Register a service instance.
    
    Called by services on startup to register themselves.
    Returns the instance_id which should be used for heartbeats and deregistration.
    """
    instance_id = str(uuid4())
    current_time = time.time()
    current_timestamp = datetime.now(timezone.utc).isoformat()
    
    instance_data = {
        "instance_id": instance_id,
        "service_name": registration.service_name,
        "base_url": str(registration.base_url),
        "registered_at": current_time,
        "last_heartbeat": current_time,
        "registered_at_iso": current_timestamp,
        "last_heartbeat_iso": current_timestamp,
    }
    
    async with _registry_lock:
        if registration.service_name not in _registry:
            _registry[registration.service_name] = []
        _registry[registration.service_name].append(instance_data)
    
    return ServiceInstance(
        instance_id=instance_id,
        service_name=registration.service_name,
        base_url=str(registration.base_url),
        registered_at=current_timestamp,
        last_heartbeat=current_timestamp,
    )


@app.post("/heartbeat/{instance_id}", status_code=status.HTTP_200_OK)
async def heartbeat(instance_id: str):
    """
    Update the last heartbeat timestamp for an instance.
    
    Services should call this periodically (e.g., every 10-15 seconds)
    to keep themselves registered. If an instance doesn't send a heartbeat
    within HEARTBEAT_TIMEOUT seconds, it will be removed.
    """
    current_time = time.time()
    current_timestamp = datetime.now(timezone.utc).isoformat()
    
    async with _registry_lock:
        found = False
        for service_name, instances in _registry.items():
            for inst in instances:
                if inst["instance_id"] == instance_id:
                    inst["last_heartbeat"] = current_time
                    inst["last_heartbeat_iso"] = current_timestamp
                    found = True
                    break
            if found:
                break
    
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )
    
    return {"status": "ok", "instance_id": instance_id}


@app.delete("/deregister/{instance_id}", status_code=status.HTTP_200_OK)
async def deregister_service(instance_id: str):
    """
    Deregister a service instance.
    
    Called by services on shutdown to remove themselves from the registry.
    """
    async with _registry_lock:
        found = False
        for service_name in list(_registry.keys()):
            instances = _registry[service_name]
            _registry[service_name] = [
                inst for inst in instances if inst["instance_id"] != instance_id
            ]
            
            if _registry[service_name] and any(inst["instance_id"] == instance_id for inst in instances):
                found = True
                break
            elif not _registry[service_name]:
                # Remove service if no instances left
                del _registry[service_name]
                if any(inst["instance_id"] == instance_id for inst in instances):
                    found = True
                    break
    
    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Instance {instance_id} not found"
        )
    
    return {"status": "ok", "instance_id": instance_id}


@app.get("/services/{service_name}", response_model=ServiceList)
async def get_service_instances(service_name: str):
    """
    Get all active instances of a service.
    
    Returns a list of all registered instances for the given service name.
    """
    current_time = time.time()
    
    async with _registry_lock:
        if service_name not in _registry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service '{service_name}' not found"
            )
        
        # Filter to only active instances
        instances = [
            inst for inst in _registry[service_name]
            if current_time - inst["last_heartbeat"] < HEARTBEAT_TIMEOUT
        ]
        
        if not instances:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No active instances for service '{service_name}'"
            )
        
        # Convert to response models
        service_instances = [
            ServiceInstance(
                instance_id=inst["instance_id"],
                service_name=inst["service_name"],
                base_url=inst["base_url"],
                registered_at=inst["registered_at_iso"],
                last_heartbeat=inst["last_heartbeat_iso"],
            )
            for inst in instances
        ]
    
    return ServiceList(
        service_name=service_name,
        instances=service_instances,
        count=len(service_instances),
    )


@app.get("/services", response_model=Dict[str, ServiceList])
async def list_all_services():
    """Get all registered services and their instances."""
    current_time = time.time()
    result = {}
    
    async with _registry_lock:
        for service_name, instances in _registry.items():
            # Filter to only active instances
            active_instances = [
                inst for inst in instances
                if current_time - inst["last_heartbeat"] < HEARTBEAT_TIMEOUT
            ]
            
            if active_instances:
                service_instances = [
                    ServiceInstance(
                        instance_id=inst["instance_id"],
                        service_name=inst["service_name"],
                        base_url=inst["base_url"],
                        registered_at=inst["registered_at_iso"],
                        last_heartbeat=inst["last_heartbeat_iso"],
                    )
                    for inst in active_instances
                ]
                
                result[service_name] = ServiceList(
                    service_name=service_name,
                    instances=service_instances,
                    count=len(service_instances),
                )
    
    return result


@app.get("/status", response_model=RegistryStatus)
async def get_registry_status():
    """Get overall registry status and statistics."""
    current_time = time.time()
    total_instances = 0
    services_dict = {}
    
    async with _registry_lock:
        for service_name, instances in _registry.items():
            # Count only active instances
            active_count = sum(
                1 for inst in instances
                if current_time - inst["last_heartbeat"] < HEARTBEAT_TIMEOUT
            )
            if active_count > 0:
                services_dict[service_name] = active_count
                total_instances += active_count
    
    return RegistryStatus(
        status="ok",
        total_services=len(services_dict),
        total_instances=total_instances,
        services=services_dict,
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "registry"}


@app.get("/")
async def root():
    """Root endpoint with registry information."""
    return {
        "service": "Service Registry",
        "version": "1.0.0",
        "endpoints": {
            "register": "/register",
            "heartbeat": "/heartbeat/{instance_id}",
            "deregister": "/deregister/{instance_id}",
            "get_service": "/services/{service_name}",
            "list_all": "/services",
            "status": "/status",
        },
        "docs": "/docs",
    }

