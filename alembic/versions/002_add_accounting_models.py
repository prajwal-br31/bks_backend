"""Add accounting models

Revision ID: 002_accounting
Revises: 001_initial
Create Date: 2025-12-07
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '002_accounting'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enums (with IF NOT EXISTS check)
    op.execute("DO $$ BEGIN CREATE TYPE accounttype AS ENUM ('asset', 'liability', 'equity', 'revenue', 'expense'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE sourcemodule AS ENUM ('ar', 'ap', 'bank', 'manual', 'system'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE journalstatus AS ENUM ('draft', 'posted', 'void'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE invoicestatus AS ENUM ('draft', 'sent', 'partially_paid', 'paid', 'void'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    op.execute("DO $$ BEGIN CREATE TYPE billstatus AS ENUM ('draft', 'approved', 'partially_paid', 'paid', 'void'); EXCEPTION WHEN duplicate_object THEN null; END $$;")
    
    # Chart of Accounts
    op.create_table(
        'chart_of_accounts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('code', sa.String(50), nullable=False),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('account_type', postgresql.ENUM('asset', 'liability', 'equity', 'revenue', 'expense', name='accounttype', create_type=False), nullable=False),
        sa.Column('is_cash', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_chart_of_accounts_company_code', 'chart_of_accounts', ['company_id', 'code'])
    
    # Journal Entries
    op.create_table(
        'journal_entries',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('source_module', postgresql.ENUM('ar', 'ap', 'bank', 'manual', 'system', name='sourcemodule', create_type=False), nullable=False),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('status', postgresql.ENUM('draft', 'posted', 'void', name='journalstatus', create_type=False), nullable=False, server_default='draft'),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    # Journal Lines
    op.create_table(
        'journal_lines',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('journal_entry_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('account_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('description', sa.String(500), nullable=True),
        sa.Column('debit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('credit', sa.Numeric(18, 2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['account_id'], ['chart_of_accounts.id']),
        sa.CheckConstraint('debit >= 0', name='check_debit_non_negative'),
        sa.CheckConstraint('credit >= 0', name='check_credit_non_negative')
    )
    
    # AR Invoices
    op.create_table(
        'ar_invoices',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invoice_number', sa.String(100), nullable=False),
        sa.Column('invoice_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', postgresql.ENUM('draft', 'sent', 'partially_paid', 'paid', 'void', name='invoicestatus', create_type=False), nullable=False, server_default='draft'),
        sa.Column('currency', sa.String(10), nullable=False, server_default='USD'),
        sa.Column('total_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('balance_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('contact_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('journal_entry_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    # AR Receipts
    op.create_table(
        'ar_receipts',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('receipt_number', sa.String(100), nullable=False),
        sa.Column('receipt_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('payment_method', sa.String(50), nullable=True),
        sa.Column('contact_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('invoice_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('journal_entry_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    # AP Bills
    op.create_table(
        'ap_bills',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bill_number', sa.String(100), nullable=False),
        sa.Column('bill_date', sa.Date(), nullable=False),
        sa.Column('due_date', sa.Date(), nullable=True),
        sa.Column('status', postgresql.ENUM('draft', 'approved', 'partially_paid', 'paid', 'void', name='billstatus', create_type=False), nullable=False, server_default='draft'),
        sa.Column('currency', sa.String(10), nullable=False, server_default='USD'),
        sa.Column('total_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('balance_amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('contact_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('journal_entry_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )
    
    # AP Payments
    op.create_table(
        'ap_payments',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('company_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('payment_number', sa.String(100), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('amount', sa.Numeric(18, 2), nullable=False),
        sa.Column('payment_method', sa.String(50), nullable=True),
        sa.Column('contact_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('bill_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('journal_entry_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('ap_payments')
    op.drop_table('ap_bills')
    op.drop_table('ar_receipts')
    op.drop_table('ar_invoices')
    op.drop_table('journal_lines')
    op.drop_table('journal_entries')
    op.drop_table('chart_of_accounts')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS billstatus")
    op.execute("DROP TYPE IF EXISTS invoicestatus")
    op.execute("DROP TYPE IF EXISTS journalstatus")
    op.execute("DROP TYPE IF EXISTS sourcemodule")
    op.execute("DROP TYPE IF EXISTS accounttype")

