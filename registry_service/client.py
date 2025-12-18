"""
Service Registry Client

Helper module for services to register themselves with the service registry
and send periodic heartbeats.
"""

import asyncio
import os
import signal
import sys
from typing import Optional

import httpx


class ServiceRegistryClient:
    """
    Client for registering a service with the service registry.
    
    Usage:
        client = ServiceRegistryClient(
            service_name="users",
            base_url="http://localhost:8000",
            registry_url="http://localhost:5000"
        )
        await client.register()
        # Service is now registered
        # Heartbeats are sent automatically in the background
    """
    
    def __init__(
        self,
        service_name: str,
        base_url: str,
        registry_url: Optional[str] = None,
        heartbeat_interval: int = 10,
    ):
        """
        Initialize the service registry client.
        
        Args:
            service_name: Name of the service (e.g., 'users', 'timelines', 'likes')
            base_url: Base URL of this service instance (e.g., 'http://localhost:8000')
            registry_url: URL of the service registry (defaults to REGISTRY_URL env var or http://localhost:5000)
            heartbeat_interval: Seconds between heartbeats (default: 10)
        """
        self.service_name = service_name
        self.base_url = base_url
        self.registry_url = registry_url or os.getenv("REGISTRY_URL", "http://localhost:5000")
        self.heartbeat_interval = heartbeat_interval
        self.instance_id: Optional[str] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
    
    async def register(self) -> str:
        """
        Register this service instance with the registry.
        
        Returns:
            The instance_id assigned by the registry
        """
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.registry_url}/register",
                json={
                    "service_name": self.service_name,
                    "base_url": self.base_url,
                },
                timeout=5.0,
            )
            response.raise_for_status()
            data = response.json()
            self.instance_id = data["instance_id"]
            
            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            
            return self.instance_id
    
    async def _heartbeat_loop(self):
        """Background task to send periodic heartbeats."""
        while not self._shutdown_event.is_set():
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self.instance_id:
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            f"{self.registry_url}/heartbeat/{self.instance_id}",
                            timeout=5.0,
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                # Log error but continue trying
                pass
    
    async def deregister(self):
        """Deregister this service instance from the registry."""
        if self._heartbeat_task:
            self._shutdown_event.set()
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        
        if self.instance_id:
            try:
                async with httpx.AsyncClient() as client:
                    await client.delete(
                        f"{self.registry_url}/deregister/{self.instance_id}",
                        timeout=5.0,
                    )
            except Exception:
                # Best effort - service is shutting down anyway
                pass


# Global client instance (for use in FastAPI startup/shutdown)
_registry_client: Optional[ServiceRegistryClient] = None


async def register_service(service_name: str, base_url: str, registry_url: Optional[str] = None):
    """
    Convenience function to register a service.
    
    Usage in FastAPI:
        @app.on_event("startup")
        async def startup():
            await register_service("users", "http://localhost:8000")
    """
    global _registry_client
    _registry_client = ServiceRegistryClient(service_name, base_url, registry_url)
    await _registry_client.register()
    return _registry_client.instance_id


async def deregister_service():
    """Convenience function to deregister a service."""
    global _registry_client
    if _registry_client:
        await _registry_client.deregister()
        _registry_client = None

