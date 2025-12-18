"""
Service Discovery Helper

Functions to query the service registry and get service URLs.
"""

import os
from typing import Optional
import httpx


REGISTRY_URL = os.getenv("REGISTRY_URL", "http://localhost:5000")


async def get_service_url(service_name: str) -> Optional[str]:
    """
    Get a service URL from the registry.
    
    Args:
        service_name: Name of the service (e.g., 'users', 'timelines', 'likes', 'polls')
    
    Returns:
        Base URL of the first available service instance (e.g., 'http://localhost:8000')
        Returns None if service not found or no active instances
    """
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.get(f"{REGISTRY_URL}/services/{service_name}")
            response.raise_for_status()
            data = response.json()
            instances = data.get("instances", [])
            
            if not instances:
                return None
            
            # Return the first available instance
            return instances[0]["base_url"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception:
            return None


def get_service_url_sync(service_name: str) -> Optional[str]:
    """
    Synchronous version of get_service_url (for use in non-async contexts).
    
    Note: This blocks the event loop. Prefer the async version when possible.
    """
    with httpx.Client(timeout=5.0) as client:
        try:
            response = client.get(f"{REGISTRY_URL}/services/{service_name}")
            response.raise_for_status()
            data = response.json()
            instances = data.get("instances", [])
            
            if not instances:
                return None
            
            # Return the first available instance
            return instances[0]["base_url"]
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise
        except Exception:
            return None

