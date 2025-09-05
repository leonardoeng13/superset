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

"""Tenant Context Middleware for Multi-Tenant Superset"""

from __future__ import annotations

import logging
from typing import Optional

from flask import Flask, g, request

logger = logging.getLogger(__name__)


class TenantContextMiddleware:
    """
    WSGI middleware to extract and set tenant context for each request.
    
    This middleware extracts tenant information from various sources:
    - Subdomain (e.g., tenant1.superset.com)
    - OIDC/JWT claims  
    - Request headers (X-Tenant-ID)
    - User attributes
    """
    
    def __init__(self, app: Flask):
        """
        Initialize middleware with Flask app.
        
        :param app: Flask application instance
        """
        self.app = app
        self.tenant_header = app.config.get("TENANT_HEADER", "X-Tenant-ID")
        self.enable_subdomain_routing = app.config.get("ENABLE_SUBDOMAIN_TENANT_ROUTING", False)
        self.default_tenant = app.config.get("DEFAULT_TENANT_ID")
        
    def extract_tenant_from_subdomain(self, host: str) -> Optional[str]:
        """
        Extract tenant ID from subdomain.
        
        :param host: Request host header
        :returns: Tenant ID or None
        """
        if not self.enable_subdomain_routing or not host:
            return None
            
        parts = host.split(".")
        if len(parts) > 2:  # has subdomain
            subdomain = parts[0].lower()
            
            # Exclude common subdomains that aren't tenants
            excluded = {"www", "api", "admin", "static", "cdn"}
            if subdomain not in excluded:
                return subdomain
        
        return None
    
    def extract_tenant_from_oidc_claims(self) -> Optional[str]:
        """
        Extract tenant ID from OIDC/JWT claims in current user.
        
        :returns: Tenant ID or None
        """
        if not hasattr(g, "user") or not g.user:
            return None
        
        try:
            # Check user's extra attributes for OIDC claims
            if hasattr(g.user, "extra") and g.user.extra:
                import json
                user_extra = json.loads(g.user.extra) if isinstance(g.user.extra, str) else g.user.extra
                
                # Check common OIDC claim names
                tenant_claims = ["tenant_id", "tenant", "org_id", "organization", "company_id"]
                for claim in tenant_claims:
                    if claim in user_extra:
                        return str(user_extra[claim])
            
            # Check if user model has direct tenant_id attribute
            if hasattr(g.user, "tenant_id") and g.user.tenant_id:
                return str(g.user.tenant_id)
                
        except (json.JSONDecodeError, AttributeError, TypeError) as ex:
            logger.warning("Failed to extract tenant from OIDC claims: %s", ex)
        
        return None
    
    def set_tenant_context(self) -> None:
        """
        Extract tenant ID and set it in Flask g context.
        
        Priority order:
        1. Request header (X-Tenant-ID)
        2. Subdomain (if enabled)
        3. OIDC/JWT claims
        4. Default tenant (if configured)
        """
        tenant_id = None
        source = "none"
        
        # 1. Check request headers first (highest priority)
        header_tenant = request.headers.get(self.tenant_header)
        if header_tenant:
            tenant_id = header_tenant.strip()
            source = "header"
        
        # 2. Check subdomain
        if not tenant_id:
            subdomain_tenant = self.extract_tenant_from_subdomain(request.host)
            if subdomain_tenant:
                tenant_id = subdomain_tenant
                source = "subdomain"
        
        # 3. Check OIDC claims
        if not tenant_id:
            oidc_tenant = self.extract_tenant_from_oidc_claims()
            if oidc_tenant:
                tenant_id = oidc_tenant
                source = "oidc"
        
        # 4. Use default tenant if configured
        if not tenant_id and self.default_tenant:
            tenant_id = self.default_tenant
            source = "default"
        
        # Set in Flask g context
        g.tenant_id = tenant_id
        g.tenant_source = source
        
        if tenant_id:
            logger.debug("Set tenant context: %s (source: %s)", tenant_id, source)
        else:
            logger.warning("No tenant ID found for request to %s", request.url)


def init_tenant_middleware(app: Flask) -> None:
    """
    Initialize tenant context middleware for Flask app.
    
    :param app: Flask application instance
    """
    # Register before request handler to set tenant context
    @app.before_request
    def set_tenant_context():
        """Set tenant context before each request."""
        middleware = TenantContextMiddleware(app)
        middleware.set_tenant_context()
    
    logger.info("Tenant context middleware initialized")
