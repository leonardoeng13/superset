# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""Tenant Management Utilities for Multi-Tenant Superset"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Optional

from flask import current_app, g
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url, URL
from sqlalchemy.pool import StaticPool

from superset.extensions import cache_manager

logger = logging.getLogger(__name__)


class TenantManager:
    """
    Utility class for managing tenant-specific operations like
    database connections, cache keys, and tenant validation.
    """
    
    @staticmethod
    def get_current_tenant_id() -> Optional[str]:
        """
        Get current tenant ID from Flask g context.
        
        :returns: Current tenant ID or None
        """
        return getattr(g, "tenant_id", None)
    
    @staticmethod
    @lru_cache(maxsize=100)
    def is_valid_tenant(tenant_id: str) -> bool:
        """
        Validate if tenant_id exists and is active.
        
        This method can be extended to check against a tenant registry table.
        For now, it performs basic validation.
        
        :param tenant_id: Tenant ID to validate
        :returns: True if tenant is valid
        """
        if not tenant_id or not isinstance(tenant_id, str):
            return False
        
        # Basic validation rules
        if len(tenant_id) < 2 or len(tenant_id) > 50:
            return False
        
        # Allow alphanumeric, hyphens, underscores
        if not tenant_id.replace("-", "").replace("_", "").isalnum():
            return False
        
        # TODO: Check against tenant registry table
        # from superset.models.tenant import TenantRegistry
        # return TenantRegistry.query.filter_by(
        #     tenant_id=tenant_id, 
        #     is_active=True
        # ).count() > 0
        
        return True
    
    @staticmethod
    def get_tenant_cache_key(base_key: str, tenant_id: Optional[str] = None) -> str:
        """
        Generate tenant-aware cache key.
        
        :param base_key: Base cache key
        :param tenant_id: Tenant ID (uses current if None)
        :returns: Tenant-prefixed cache key
        """
        if tenant_id is None:
            tenant_id = TenantManager.get_current_tenant_id()
        
        if tenant_id:
            return f"tenant:{tenant_id}:{base_key}"
        
        return f"global:{base_key}"
    
    @staticmethod
    def get_tenant_database_uri(
        base_uri: str, 
        tenant_id: str,
        schema_name: Optional[str] = None
    ) -> str:
        """
        Generate tenant-specific database URI with search_path.
        
        :param base_uri: Base database URI
        :param tenant_id: Tenant ID
        :param schema_name: Optional schema name (defaults to tenant_id)
        :returns: Modified URI with tenant search_path
        """
        if not schema_name:
            schema_name = tenant_id
        
        url = make_url(base_uri)
        
        # For PostgreSQL, add search_path to connect_args
        if url.drivername.startswith("postgresql"):
            # Parse existing connect_args if any
            connect_args = {}
            if url.query:
                # Handle existing query parameters
                for key, value in url.query.items():
                    if key == "options":
                        connect_args["options"] = value
                    else:
                        connect_args[key] = value
            
            # Set search_path
            options = connect_args.get("options", "")
            search_path_option = f"-c search_path={schema_name},public"
            
            if options:
                connect_args["options"] = f"{options} {search_path_option}"
            else:
                connect_args["options"] = search_path_option
            
            # Rebuild URL with connect_args
            query = {k: v for k, v in connect_args.items() if k != "options"}
            if connect_args.get("options"):
                query["options"] = connect_args["options"]
                
            return url.set(query=query).__str__()
        
        return base_uri
    
    @staticmethod
    def create_tenant_engine(
        database_uri: str,
        tenant_id: str,
        **engine_kwargs: Any,
    ) -> Engine:
        """
        Create SQLAlchemy engine with tenant-specific configuration.
        
        :param database_uri: Database URI
        :param tenant_id: Tenant ID
        :param engine_kwargs: Additional engine arguments
        :returns: Configured SQLAlchemy engine
        """
        tenant_uri = TenantManager.get_tenant_database_uri(database_uri, tenant_id)
        
        # Default engine configuration
        default_kwargs = {
            "pool_pre_ping": True,
            "pool_recycle": current_app.config.get("SQLALCHEMY_POOL_RECYCLE", 300),
            "echo": current_app.config.get("SQLALCHEMY_ECHO", False),
        }
        
        # Merge with provided kwargs
        engine_config = {**default_kwargs, **engine_kwargs}
        
        engine = create_engine(tenant_uri, **engine_config)
        
        # Add event listener to set search_path for PostgreSQL
        if make_url(tenant_uri).drivername.startswith("postgresql"):
            from sqlalchemy import event
            
            @event.listens_for(engine, "connect")
            def set_search_path(dbapi_connection, connection_record):
                """Set search_path on connection."""
                with dbapi_connection.cursor() as cursor:
                    cursor.execute(f"SET search_path TO {tenant_id}, public")
        
        logger.info("Created tenant engine for tenant %s", tenant_id)
        return engine
    
    @staticmethod
    def get_tenant_filter_clause(model_class, tenant_id: Optional[str] = None):
        """
        Get SQLAlchemy filter clause for tenant isolation.
        
        :param model_class: SQLAlchemy model class
        :param tenant_id: Tenant ID (uses current if None)
        :returns: SQLAlchemy filter clause or None
        """
        if tenant_id is None:
            tenant_id = TenantManager.get_current_tenant_id()
        
        if tenant_id and hasattr(model_class, "tenant_id"):
            return model_class.tenant_id == tenant_id
        
        return None
    
    @staticmethod
    def clear_tenant_cache(tenant_id: str) -> None:
        """
        Clear all cache entries for a specific tenant.
        
        :param tenant_id: Tenant ID
        """
        cache_prefix = f"tenant:{tenant_id}:"
        
        if hasattr(cache_manager.cache, "delete_many"):
            # Redis or similar cache backends
            cache = cache_manager.cache
            if hasattr(cache.cache, "scan_iter"):  # Redis
                keys_to_delete = []
                for key in cache.cache.scan_iter(match=f"{cache_prefix}*"):
                    keys_to_delete.append(key)
                
                if keys_to_delete:
                    cache.cache.delete(*keys_to_delete)
                    logger.info("Cleared %d cache entries for tenant %s", len(keys_to_delete), tenant_id)
            else:
                logger.warning("Cache backend doesn't support pattern-based deletion")
        else:
            logger.warning("Cache backend doesn't support batch deletion")
    
    @staticmethod
    def validate_tenant_access(resource_tenant_id: Optional[str]) -> bool:
        """
        Validate if current user can access resource belonging to tenant.
        
        :param resource_tenant_id: Tenant ID of the resource
        :returns: True if access is allowed
        """
        current_tenant = TenantManager.get_current_tenant_id()
        
        # Admin users with no tenant context can access all
        if current_tenant is None:
            from superset import security_manager
            return security_manager.is_admin()
        
        # Resource must belong to current tenant
        return current_tenant == resource_tenant_id


# Cache instance for tenant manager
tenant_manager = TenantManager()