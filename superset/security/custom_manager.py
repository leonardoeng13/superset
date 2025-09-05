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

"""Custom Security Manager for Multi-Tenant Superset"""

from __future__ import annotations

import logging
from typing import Any, Optional, TYPE_CHECKING

from flask import g, request
from sqlalchemy import and_

from superset.security.manager import SupersetSecurityManager
from superset.utils import core as utils
from superset.utils.filters import get_dataset_access_filters

if TYPE_CHECKING:
    from superset.connectors.sqla.models import BaseDatasource, SqlaTable
    from superset.models.core import Database
    from superset.models.dashboard import Dashboard
    from superset.models.slice import Slice
    from superset.utils.core import DatasourceName

logger = logging.getLogger(__name__)


class MultiTenantSecurityManager(SupersetSecurityManager):
    """
    Multi-tenant security manager that extends SupersetSecurityManager
    to provide tenant isolation for databases, datasets, charts, and dashboards.
    """

    def get_current_tenant_id(self) -> Optional[str]:
        """
        Extract tenant_id from request context.
        
        This method checks multiple sources for tenant_id:
        1. Flask g context (set by middleware)
        2. OIDC/JWT claims in request
        3. Subdomain extraction (for subdomain-based routing)
        
        :returns: Current tenant_id or None
        """
        # Check if tenant_id is already set in Flask g context
        if hasattr(g, "tenant_id") and g.tenant_id:
            return g.tenant_id
        
        # Extract from OIDC/JWT claims
        if hasattr(g, "user") and g.user:
            # Check for tenant_id in user attributes or OIDC claims
            if hasattr(g.user, "tenant_id") and g.user.tenant_id:
                return g.user.tenant_id
            
            # Check user's custom properties
            if hasattr(g.user, "extra") and g.user.extra:
                import json
                try:
                    user_extra = json.loads(g.user.extra) if isinstance(g.user.extra, str) else g.user.extra
                    if "tenant_id" in user_extra:
                        return user_extra["tenant_id"]
                except (json.JSONDecodeError, TypeError):
                    pass
        
        # Extract from subdomain if configured
        if hasattr(request, "host") and request.host:
            subdomain = request.host.split('.')[0]
            if subdomain and subdomain != "www":
                # Validate subdomain is a valid tenant
                # This would integrate with your tenant registry
                return subdomain
        
        # Admin users can optionally bypass tenant isolation
        if self.is_admin():
            # Check if admin wants to impersonate a tenant via header
            tenant_header = request.headers.get("X-Tenant-ID")
            if tenant_header:
                return tenant_header
            
            # For admin users, return None to see all tenants (configurable)
            admin_see_all = utils.get_from_request_config("ADMIN_SEE_ALL_TENANTS", True)
            if admin_see_all:
                return None
        
        logger.warning("No tenant_id found for user %s", g.user.username if hasattr(g, "user") else "anonymous")
        return None

    def get_user_datasources(self) -> list["BaseDatasource"]:
        """
        Override to filter datasources by tenant.
        
        :returns: List of datasources accessible to current tenant
        """
        tenant_id = self.get_current_tenant_id()
        
        # If no tenant (admin with see-all enabled), use parent method
        if tenant_id is None:
            return super().get_user_datasources()
        
        user_datasources = set()
        
        # pylint: disable=import-outside-toplevel
        from superset.connectors.sqla.models import SqlaTable
        
        # Filter datasets by tenant_id
        query = (
            self.get_session.query(SqlaTable)
            .filter(get_dataset_access_filters(SqlaTable))
        )
        
        # Add tenant filter if tenant_id column exists
        if hasattr(SqlaTable, "tenant_id"):
            query = query.filter(SqlaTable.tenant_id == tenant_id)
        
        user_datasources.update(query.all())
        
        # Filter databases by tenant and include their datasources
        from superset.models.core import Database
        
        databases_query = self.get_session.query(Database)
        if hasattr(Database, "tenant_id"):
            databases_query = databases_query.filter(Database.tenant_id == tenant_id)
        
        for database in databases_query:
            if self.can_access_database(database):
                # Get all datasources for this tenant's database
                datasources_for_db = (
                    self.get_session.query(SqlaTable)
                    .filter(SqlaTable.database_id == database.id)
                )
                if hasattr(SqlaTable, "tenant_id"):
                    datasources_for_db = datasources_for_db.filter(SqlaTable.tenant_id == tenant_id)
                
                user_datasources.update(datasources_for_db.all())
        
        return list(user_datasources)

    def get_datasources_accessible_by_user(
        self,
        database: "Database",
        datasource_names: list[DatasourceName],
        catalog: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> list[DatasourceName]:
        """
        Override to filter datasources by tenant.
        
        :param database: The SQL database
        :param datasource_names: List of eligible SQL tables w/ schema
        :param catalog: Fallback SQL catalog if not present in table name
        :param schema: Fallback SQL schema if not present in table name
        :returns: List of accessible SQL tables w/ schema filtered by tenant
        """
        tenant_id = self.get_current_tenant_id()
        
        # Ensure database belongs to current tenant
        if tenant_id is not None and hasattr(database, "tenant_id"):
            if database.tenant_id != tenant_id:
                return []
        
        # Use parent method for actual permission checking
        return super().get_datasources_accessible_by_user(
            database, datasource_names, catalog, schema
        )

    def can_access_database(self, database: "Database") -> bool:
        """
        Override to add tenant validation to database access.
        
        :param database: The database
        :returns: Whether current tenant can access the database
        """
        tenant_id = self.get_current_tenant_id()
        
        # Check tenant isolation first
        if tenant_id is not None and hasattr(database, "tenant_id"):
            if database.tenant_id != tenant_id:
                return False
        
        # Use parent method for standard permission checking
        return super().can_access_database(database)

    def can_access_datasource(self, datasource: "BaseDatasource") -> bool:
        """
        Override to add tenant validation to datasource access.
        
        :param datasource: The datasource
        :returns: Whether current tenant can access the datasource
        """
        tenant_id = self.get_current_tenant_id()
        
        # Check tenant isolation first
        if tenant_id is not None and hasattr(datasource, "tenant_id"):
            if datasource.tenant_id != tenant_id:
                return False
        
        # Also check if the datasource's database belongs to the tenant
        if hasattr(datasource, "database") and hasattr(datasource.database, "tenant_id"):
            if tenant_id is not None and datasource.database.tenant_id != tenant_id:
                return False
        
        # Use parent method for standard permission checking
        return super().can_access_datasource(datasource)

    def raise_for_access(
        self,
        dashboard: Optional["Dashboard"] = None,
        chart: Optional["Slice"] = None,
        database: Optional["Database"] = None,
        datasource: Optional["BaseDatasource"] = None,
        **kwargs: Any,
    ) -> None:
        """
        Override to add tenant validation before standard access checks.
        
        :param dashboard: The dashboard
        :param chart: The chart
        :param database: The database  
        :param datasource: The datasource
        :param kwargs: Additional arguments
        :raises SupersetSecurityException: If tenant access is denied
        """
        from superset.exceptions import SupersetSecurityException
        
        tenant_id = self.get_current_tenant_id()
        
        # Validate tenant access for each resource type
        if tenant_id is not None:
            if dashboard and hasattr(dashboard, "tenant_id"):
                if dashboard.tenant_id != tenant_id:
                    raise SupersetSecurityException(
                        f"Access denied: Dashboard {dashboard.id} not accessible to tenant {tenant_id}"
                    )
            
            if chart and hasattr(chart, "tenant_id"):
                if chart.tenant_id != tenant_id:
                    raise SupersetSecurityException(
                        f"Access denied: Chart {chart.id} not accessible to tenant {tenant_id}"
                    )
            
            if database and hasattr(database, "tenant_id"):
                if database.tenant_id != tenant_id:
                    raise SupersetSecurityException(
                        f"Access denied: Database {database.id} not accessible to tenant {tenant_id}"
                    )
            
            if datasource and hasattr(datasource, "tenant_id"):
                if datasource.tenant_id != tenant_id:
                    raise SupersetSecurityException(
                        f"Access denied: Datasource {datasource.id} not accessible to tenant {tenant_id}"
                    )
        
        # Call parent method for standard access validation
        super().raise_for_access(
            dashboard=dashboard,
            chart=chart,
            database=database,
            datasource=datasource,
            **kwargs,
        )