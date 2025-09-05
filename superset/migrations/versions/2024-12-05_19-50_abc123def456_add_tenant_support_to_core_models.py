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
"""add_tenant_support_to_core_models

Revision ID: 2024-12-05_19-50_abc123def456
Revises: c233f5365c9e
Create Date: 2024-12-05 19:50:00.000000

"""

import sqlalchemy as sa
from alembic import op

from superset.migrations.shared.utils import (
    add_columns,
    create_index,
    table_exists,
)

# revision identifiers, used by Alembic.
revision = "2024-12-05_19-50_abc123def456"
down_revision = "c233f5365c9e"


def upgrade():
    """Add tenant_id columns to core tables for multi-tenant support."""
    
    # Add tenant_id column to databases table
    if table_exists("dbs"):
        add_columns(
            "dbs",
            sa.Column("tenant_id", sa.String(255), nullable=True),
        )
        # Create index for tenant filtering
        create_index("ix_dbs_tenant_id", "dbs", ["tenant_id"])
    
    # Add tenant_id column to dashboards table
    if table_exists("dashboards"):
        add_columns(
            "dashboards", 
            sa.Column("tenant_id", sa.String(255), nullable=True),
        )
        create_index("ix_dashboards_tenant_id", "dashboards", ["tenant_id"])
    
    # Add tenant_id column to slices (charts) table
    if table_exists("slices"):
        add_columns(
            "slices",
            sa.Column("tenant_id", sa.String(255), nullable=True),
        )
        create_index("ix_slices_tenant_id", "slices", ["tenant_id"])
    
    # Add tenant_id column to tables (datasets) table
    if table_exists("tables"):
        add_columns(
            "tables",
            sa.Column("tenant_id", sa.String(255), nullable=True),
        )
        create_index("ix_tables_tenant_id", "tables", ["tenant_id"])
    
    # Add tenant_id column to saved_query table
    if table_exists("saved_query"):
        add_columns(
            "saved_query",
            sa.Column("tenant_id", sa.String(255), nullable=True),
        )
        create_index("ix_saved_query_tenant_id", "saved_query", ["tenant_id"])
    
    # Create tenant_registry table for tenant management
    op.create_table(
        "tenant_registry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(255), nullable=False, unique=True),
        sa.Column("tenant_name", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, default=True),
        sa.Column("database_schema", sa.String(255), nullable=True),
        sa.Column("configuration", sa.Text(), nullable=True),  # JSON config
        sa.Column("created_on", sa.DateTime(), nullable=True),
        sa.Column("changed_on", sa.DateTime(), nullable=True),
        sa.Column("created_by_fk", sa.Integer(), nullable=True),
        sa.Column("changed_by_fk", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["created_by_fk"], ["ab_user.id"]),
        sa.ForeignKeyConstraint(["changed_by_fk"], ["ab_user.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id"),
    )
    
    # Create indexes on tenant_registry
    create_index("ix_tenant_registry_tenant_id", "tenant_registry", ["tenant_id"])
    create_index("ix_tenant_registry_is_active", "tenant_registry", ["is_active"])


def downgrade():
    """Remove tenant support columns and table."""
    
    # Drop tenant_registry table
    op.drop_table("tenant_registry")
    
    # Remove tenant_id columns from tables (in reverse order)
    tables_to_modify = [
        "saved_query",
        "tables", 
        "slices",
        "dashboards",
        "dbs",
    ]
    
    for table_name in tables_to_modify:
        if table_exists(table_name):
            # Drop index first
            try:
                op.drop_index(f"ix_{table_name}_tenant_id")
            except Exception:
                pass  # Index might not exist
            
            # Drop column
            try:
                op.drop_column(table_name, "tenant_id")
            except Exception:
                pass  # Column might not exist