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
"""Tests for multi-tenant security manager"""

from unittest.mock import Mock, patch

import pytest
from flask import g

from superset.security.custom_manager import MultiTenantSecurityManager
from superset.utils.tenant_manager import TenantManager


class TestMultiTenantSecurityManager:
    """Test cases for MultiTenantSecurityManager"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.security_manager = MultiTenantSecurityManager()
    
    def test_get_current_tenant_id_from_flask_g(self):
        """Test tenant ID extraction from Flask g context"""
        with patch("superset.security.custom_manager.g") as mock_g:
            mock_g.tenant_id = "tenant1"
            
            tenant_id = self.security_manager.get_current_tenant_id()
            
            assert tenant_id == "tenant1"
    
    def test_get_current_tenant_id_from_user_extra(self):
        """Test tenant ID extraction from user extra attributes"""
        with patch("superset.security.custom_manager.g") as mock_g:
            # No tenant_id in g
            mock_g.tenant_id = None
            
            # Mock user with tenant in extra
            mock_user = Mock()
            mock_user.tenant_id = None
            mock_user.extra = '{"tenant_id": "tenant2"}'
            mock_g.user = mock_user
            
            tenant_id = self.security_manager.get_current_tenant_id()
            
            assert tenant_id == "tenant2"
    
    def test_get_current_tenant_id_admin_no_tenant(self):
        """Test that admin users with no tenant can see all"""
        with patch("superset.security.custom_manager.g") as mock_g:
            mock_g.tenant_id = None
            mock_g.user = None
            
            with patch.object(self.security_manager, "is_admin", return_value=True):
                with patch("superset.security.custom_manager.request") as mock_request:
                    mock_request.headers.get.return_value = None
                    
                    tenant_id = self.security_manager.get_current_tenant_id()
                    
                    assert tenant_id is None
    
    def test_can_access_database_with_tenant_filter(self):
        """Test database access filtering by tenant"""
        # Mock database with tenant_id
        mock_database = Mock()
        mock_database.tenant_id = "tenant1"
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant1"):
            with patch("superset.security.manager.SupersetSecurityManager.can_access_database", return_value=True):
                result = self.security_manager.can_access_database(mock_database)
                assert result is True
        
        # Test access denied for different tenant
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant2"):
            result = self.security_manager.can_access_database(mock_database)
            assert result is False
    
    def test_can_access_database_without_tenant_attr(self):
        """Test database access when database has no tenant_id attribute"""
        mock_database = Mock()
        del mock_database.tenant_id  # Remove tenant_id attribute
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant1"):
            with patch("superset.security.manager.SupersetSecurityManager.can_access_database", return_value=True):
                result = self.security_manager.can_access_database(mock_database)
                assert result is True
    
    def test_can_access_datasource_with_tenant_filter(self):
        """Test datasource access filtering by tenant"""
        # Mock datasource with tenant_id
        mock_datasource = Mock()
        mock_datasource.tenant_id = "tenant1"
        
        # Mock database without tenant_id
        mock_database = Mock()
        del mock_database.tenant_id
        mock_datasource.database = mock_database
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant1"):
            with patch("superset.security.manager.SupersetSecurityManager.can_access_datasource", return_value=True):
                result = self.security_manager.can_access_datasource(mock_datasource)
                assert result is True
        
        # Test access denied for different tenant
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant2"):
            result = self.security_manager.can_access_datasource(mock_datasource)
            assert result is False
    
    def test_raise_for_access_dashboard_tenant_validation(self):
        """Test raise_for_access validates dashboard tenant access"""
        from superset.exceptions import SupersetSecurityException
        
        mock_dashboard = Mock()
        mock_dashboard.tenant_id = "tenant1"
        mock_dashboard.id = 123
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant2"):
            with pytest.raises(SupersetSecurityException, match="Dashboard 123 not accessible"):
                self.security_manager.raise_for_access(dashboard=mock_dashboard)
    
    def test_raise_for_access_chart_tenant_validation(self):
        """Test raise_for_access validates chart tenant access"""
        from superset.exceptions import SupersetSecurityException
        
        mock_chart = Mock()
        mock_chart.tenant_id = "tenant1"
        mock_chart.id = 456
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant2"):
            with pytest.raises(SupersetSecurityException, match="Chart 456 not accessible"):
                self.security_manager.raise_for_access(chart=mock_chart)
    
    def test_raise_for_access_success_same_tenant(self):
        """Test raise_for_access succeeds for same tenant"""
        mock_dashboard = Mock()
        mock_dashboard.tenant_id = "tenant1"
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant1"):
            with patch("superset.security.manager.SupersetSecurityManager.raise_for_access"):
                # Should not raise exception
                self.security_manager.raise_for_access(dashboard=mock_dashboard)
    
    def test_get_datasources_accessible_by_user_tenant_filter(self):
        """Test get_datasources_accessible_by_user filters by tenant"""
        mock_database = Mock()
        mock_database.tenant_id = "tenant1"
        
        datasource_names = ["table1", "table2"]
        
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant1"):
            with patch("superset.security.manager.SupersetSecurityManager.get_datasources_accessible_by_user", return_value=datasource_names):
                result = self.security_manager.get_datasources_accessible_by_user(
                    mock_database, datasource_names
                )
                assert result == datasource_names
        
        # Test with different tenant - should return empty list
        with patch.object(self.security_manager, "get_current_tenant_id", return_value="tenant2"):
            result = self.security_manager.get_datasources_accessible_by_user(
                mock_database, datasource_names
            )
            assert result == []


class TestTenantManager:
    """Test cases for TenantManager utility class"""
    
    def test_get_current_tenant_id(self):
        """Test getting current tenant ID from Flask g"""
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = "test_tenant"
            
            tenant_id = TenantManager.get_current_tenant_id()
            
            assert tenant_id == "test_tenant"
    
    def test_is_valid_tenant_basic_validation(self):
        """Test basic tenant ID validation"""
        # Valid tenant IDs
        assert TenantManager.is_valid_tenant("tenant1") is True
        assert TenantManager.is_valid_tenant("tenant_123") is True
        assert TenantManager.is_valid_tenant("tenant-abc") is True
        
        # Invalid tenant IDs
        assert TenantManager.is_valid_tenant("") is False
        assert TenantManager.is_valid_tenant("a") is False  # too short
        assert TenantManager.is_valid_tenant("a" * 60) is False  # too long
        assert TenantManager.is_valid_tenant("tenant@123") is False  # invalid chars
        assert TenantManager.is_valid_tenant(None) is False
        assert TenantManager.is_valid_tenant(123) is False  # not string
    
    def test_get_tenant_cache_key(self):
        """Test tenant-aware cache key generation"""
        base_key = "user:123:profile"
        
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = "tenant1"
            
            cache_key = TenantManager.get_tenant_cache_key(base_key)
            
            assert cache_key == "tenant:tenant1:user:123:profile"
    
    def test_get_tenant_cache_key_no_tenant(self):
        """Test cache key generation when no tenant is set"""
        base_key = "global:config"
        
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = None
            
            cache_key = TenantManager.get_tenant_cache_key(base_key)
            
            assert cache_key == "global:global:config"
    
    def test_get_tenant_database_uri_postgresql(self):
        """Test PostgreSQL URI generation with search_path"""
        base_uri = "postgresql://user:pass@host:5432/db"
        tenant_id = "tenant1"
        
        result_uri = TenantManager.get_tenant_database_uri(base_uri, tenant_id)
        
        assert "options=-c%20search_path%3Dtenant1%2Cpublic" in result_uri
    
    def test_get_tenant_database_uri_non_postgresql(self):
        """Test URI generation for non-PostgreSQL databases"""
        base_uri = "mysql://user:pass@host:3306/db"
        tenant_id = "tenant1"
        
        result_uri = TenantManager.get_tenant_database_uri(base_uri, tenant_id)
        
        # Should return unchanged for non-PostgreSQL
        assert result_uri == base_uri
    
    def test_get_tenant_filter_clause(self):
        """Test SQLAlchemy filter clause generation"""
        # Mock model class with tenant_id attribute
        mock_model = Mock()
        mock_model.tenant_id = Mock()
        
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = "tenant1"
            
            filter_clause = TenantManager.get_tenant_filter_clause(mock_model)
            
            # Should create filter clause
            assert filter_clause is not None
    
    def test_get_tenant_filter_clause_no_tenant_attr(self):
        """Test filter clause when model has no tenant_id attribute"""
        mock_model = Mock()
        del mock_model.tenant_id  # Remove tenant_id attribute
        
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = "tenant1"
            
            filter_clause = TenantManager.get_tenant_filter_clause(mock_model)
            
            assert filter_clause is None
    
    def test_validate_tenant_access_same_tenant(self):
        """Test tenant access validation for same tenant"""
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = "tenant1"
            
            result = TenantManager.validate_tenant_access("tenant1")
            
            assert result is True
    
    def test_validate_tenant_access_different_tenant(self):
        """Test tenant access validation for different tenant"""
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = "tenant1"
            
            result = TenantManager.validate_tenant_access("tenant2")
            
            assert result is False
    
    def test_validate_tenant_access_admin_no_tenant(self):
        """Test admin user access when no current tenant"""
        with patch("superset.utils.tenant_manager.g") as mock_g:
            mock_g.tenant_id = None
            
            with patch("superset.utils.tenant_manager.security_manager") as mock_sm:
                mock_sm.is_admin.return_value = True
                
                result = TenantManager.validate_tenant_access("tenant1")
                
                assert result is True