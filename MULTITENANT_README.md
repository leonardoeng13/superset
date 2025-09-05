# Multi-Tenant Superset Implementation

This implementation provides multi-tenant support for Apache Superset using PostgreSQL schema isolation and OIDC authentication.

## Overview

The multi-tenant architecture provides:

- **Tenant Isolation**: Each tenant's data is isolated in separate PostgreSQL schemas
- **Security Manager**: Custom security manager filters all data access by tenant
- **OIDC Integration**: Tenant information extracted from OIDC claims
- **Cache Isolation**: Redis cache keys are tenant-prefixed
- **Middleware**: Request context automatically sets tenant information
- **Backward Compatibility**: Existing functionality remains unchanged

## Components

### 1. MultiTenantSecurityManager (`superset/security/custom_manager.py`)
Extends `SupersetSecurityManager` to filter all data access by tenant:
- Overrides `get_user_datasources()` to return only tenant's data
- Overrides `can_access_database()` to validate tenant ownership
- Overrides `raise_for_access()` to enforce tenant boundaries
- Supports admin users viewing all tenants (configurable)

### 2. Tenant Context Middleware (`superset/middleware/tenant_context.py`)
Extracts tenant information from requests:
- OIDC/JWT claims from authenticated users
- Subdomain parsing (e.g., tenant1.superset.com)
- HTTP headers (X-Tenant-ID)
- Configurable default tenant

### 3. Tenant Manager Utilities (`superset/utils/tenant_manager.py`)
Utility functions for tenant operations:
- Database connection string generation with search_path
- Cache key prefixing for isolation
- Tenant validation and filtering
- SQLAlchemy filter clause generation

### 4. Database Migration (`superset/migrations/versions/2025-09-05_19-50_add_tenant_support_to_core_models.py`)
Adds tenant support to existing tables:
- Adds `tenant_id` column to: `dbs`, `dashboards`, `slices`, `tables`, `saved_query`
- Creates `tenant_registry` table for tenant management
- Includes proper indexes for performance
- Supports rollback

### 5. Configuration Example (`docker/pythonpath_dev/superset_config_multitenant.py`)
Production-ready configuration example with:
- OIDC authentication setup
- Redis cache configuration
- PostgreSQL schema isolation
- Celery task configuration
- Security settings

## Quick Start

### 1. Enable Multi-Tenant Configuration

```bash
# Set environment variable to use multi-tenant config
export SUPERSET_CONFIG=superset_config_multitenant

# Or copy the configuration
cp docker/pythonpath_dev/superset_config_multitenant.py superset_config.py
```

### 2. Set Required Environment Variables

```bash
# Database connections
export DATABASE_URL="postgresql://superset:superset@localhost:5432/superset_metadata"
export TENANT_DATABASE_URL="postgresql://tenant_user:tenant_password@localhost:5432/alyva_DB"

# OIDC Configuration
export OIDC_CLIENT_ID="your_client_id"
export OIDC_CLIENT_SECRET="your_client_secret"
export OIDC_ISSUER_URL="https://your-keycloak.com/auth/realms/your-realm"

# Redis Configuration
export REDIS_HOST="localhost"
export REDIS_PORT="6379"

# Security
export SECRET_KEY="your_very_long_random_secret_key"
```

### 3. Run Database Migration

```bash
# Apply the migration to add tenant support
superset db upgrade
```

### 4. Configure OIDC Provider

In your OIDC provider (Keycloak, Auth0, etc.), ensure user tokens include a `tenant_id` claim:

```json
{
  "sub": "user123",
  "email": "user@tenant1.com",
  "tenant_id": "tenant1",
  "preferred_username": "user123"
}
```

### 5. Create PostgreSQL Schemas

For each tenant, create a dedicated schema:

```sql
-- Create schema for tenant1
CREATE SCHEMA tenant1;
GRANT USAGE ON SCHEMA tenant1 TO tenant_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA tenant1 TO tenant_user;

-- Create schema for tenant2  
CREATE SCHEMA tenant2;
GRANT USAGE ON SCHEMA tenant2 TO tenant_user;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA tenant2 TO tenant_user;
```

### 6. Register Tenants (Optional)

Add tenants to the registry table:

```sql
INSERT INTO tenant_registry (tenant_id, tenant_name, description, is_active, database_schema) 
VALUES 
    ('tenant1', 'Tenant One', 'First tenant organization', true, 'tenant1'),
    ('tenant2', 'Tenant Two', 'Second tenant organization', true, 'tenant2');
```

### 7. Start Superset

```bash
# Initialize and start Superset
superset init
superset run --host 0.0.0.0 --port 8088
```

## Usage Examples

### Tenant Detection via Headers

```bash
# Access as tenant1
curl -H "X-Tenant-ID: tenant1" http://localhost:8088/api/v1/database/

# Access as tenant2
curl -H "X-Tenant-ID: tenant2" http://localhost:8088/api/v1/database/
```

### Subdomain-Based Routing

```bash
# Enable in configuration
ENABLE_SUBDOMAIN_TENANT_ROUTING = True

# Access via subdomains
http://tenant1.superset.com/dashboard/
http://tenant2.superset.com/dashboard/
```

### Programmatic Tenant Access

```python
from superset.utils.tenant_manager import TenantManager

# Get current tenant
tenant_id = TenantManager.get_current_tenant_id()

# Generate tenant-specific cache key
cache_key = TenantManager.get_tenant_cache_key("user:profile", "tenant1")

# Validate tenant access
can_access = TenantManager.validate_tenant_access("resource_tenant")
```

## Configuration Options

### Tenant Middleware Settings

```python
# Enable tenant middleware
ENABLE_TENANT_MIDDLEWARE = True

# Tenant detection configuration  
TENANT_HEADER = "X-Tenant-ID"
ENABLE_SUBDOMAIN_TENANT_ROUTING = True
DEFAULT_TENANT_ID = None  # or set default tenant

# Admin access control
ADMIN_SEE_ALL_TENANTS = True  # Allow admins to see all tenants
```

### Security Manager

```python
# Use custom multi-tenant security manager
from superset.security.custom_manager import MultiTenantSecurityManager
CUSTOM_SECURITY_MANAGER = MultiTenantSecurityManager
```

### OIDC Authentication

```python
AUTH_TYPE = AUTH_OAUTH

OAUTH_PROVIDERS = [{
    "name": "keycloak",
    "remote_app": {
        "client_id": os.environ.get("OIDC_CLIENT_ID"),
        "client_secret": os.environ.get("OIDC_CLIENT_SECRET"),
        # ... other config
    },
    "custom_mapping": {
        "tenant_id": "tenant_id",  # Map OIDC claim to tenant
        "email": "email",
        "username": "preferred_username",
    },
}]
```

## Testing

Run the test suite:

```bash
# Run tenant security tests
python -m pytest tests/unit_tests/security/test_tenant_security.py -v

# Run all tests
python -m pytest tests/unit_tests/ -k tenant
```

## Architecture Decisions

### Schema-Based Isolation
- **Pros**: Native PostgreSQL security, easy to manage, good performance
- **Cons**: Single database, shared connection pool
- **Alternative**: Separate databases per tenant (more isolation, more complex)

### Request-Level Tenant Detection
- **Pros**: Flexible tenant routing, supports multiple detection methods
- **Cons**: Per-request overhead
- **Alternative**: Session-based tenant storage

### Extension vs Modification
- **Decision**: Extend existing classes rather than modify core Superset
- **Benefit**: Maintains upgrade compatibility, minimal risk
- **Trade-off**: Some duplication of filtering logic

## Performance Considerations

### Connection Pooling
- Single pool serves all tenants
- Consider separate pools for high-volume tenants
- Monitor connection usage per tenant

### Cache Performance
- Tenant-prefixed keys prevent cache pollution
- Consider separate Redis databases for large tenants
- Monitor cache hit rates per tenant

### Query Performance
- Indexes on `tenant_id` columns ensure efficient filtering
- Consider partitioning for very large multi-tenant tables
- Monitor query performance across tenants

## Security Considerations

### Data Isolation
- All data access filtered by `tenant_id`
- PostgreSQL search_path provides schema isolation
- Admin users can optionally bypass isolation

### Authentication
- OIDC integration ensures centralized authentication
- Tenant claims must be secure and tamper-proof
- Consider additional tenant validation

### Cache Isolation
- Redis keys prefixed with tenant ID
- No cross-tenant cache pollution
- Consider encrypted cache for sensitive data

## Troubleshooting

### Common Issues

1. **No tenant detected**
   - Check OIDC claims include `tenant_id`
   - Verify middleware is initialized
   - Check request headers/subdomain

2. **Database access denied**
   - Verify PostgreSQL schema permissions
   - Check search_path configuration
   - Confirm tenant_user has schema access

3. **Cache issues**
   - Monitor Redis for tenant-prefixed keys
   - Check cache configuration
   - Verify tenant isolation

### Debug Mode

```python
# Enable detailed logging
import logging
logging.getLogger('superset.security.custom_manager').setLevel(logging.DEBUG)
logging.getLogger('superset.middleware.tenant_context').setLevel(logging.DEBUG)
```

## Contributing

When adding new features:

1. **Extend, don't modify**: Follow the pattern of extending existing classes
2. **Test tenant isolation**: Ensure new features respect tenant boundaries  
3. **Update documentation**: Document any new configuration options
4. **Add tests**: Include tenant-specific test cases

## License

Licensed under the Apache License, Version 2.0. See the main Superset repository for full license terms.