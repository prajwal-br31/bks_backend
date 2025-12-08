"""006_add_document_accounting_links

Revision ID: 7855cfb0370c
Revises: a00265131a61
Create Date: 2025-12-08 03:37:39.028741
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision: str = '7855cfb0370c'
down_revision: Union[str, None] = 'a00265131a61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add accounting link columns to documents table
    op.add_column('documents', sa.Column('ar_invoice_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column('documents', sa.Column('ap_bill_id', postgresql.UUID(as_uuid=True), nullable=True))
    
    # Add indexes for faster lookups
    op.create_index('ix_documents_ar_invoice_id', 'documents', ['ar_invoice_id'])
    op.create_index('ix_documents_ap_bill_id', 'documents', ['ap_bill_id'])


def downgrade() -> None:
    # Drop indexes
    op.drop_index('ix_documents_ap_bill_id', table_name='documents')
    op.drop_index('ix_documents_ar_invoice_id', table_name='documents')
    
    # Drop columns
    op.drop_column('documents', 'ap_bill_id')
    op.drop_column('documents', 'ar_invoice_id')
