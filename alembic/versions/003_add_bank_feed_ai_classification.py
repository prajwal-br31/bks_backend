"""Add AI classification fields to bank feed

Revision ID: 003_bank_feed_ai
Revises: 002_accounting
Create Date: 2025-12-08
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import inspect

revision: str = '003_bank_feed_ai'
down_revision: Union[str, None] = '002_accounting'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    bind = op.get_bind()
    inspector = inspect(bind)
    return table_name in inspector.get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    if not table_exists(table_name):
        return False
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Create enums needed for bank feed
    op.execute("""
        DO $$ BEGIN 
            CREATE TYPE transactiontype AS ENUM ('credit', 'debit');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN 
            CREATE TYPE transactionstatus AS ENUM ('pending', 'matched', 'reviewed', 'cleared', 'reconciled', 'excluded');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN 
            CREATE TYPE matchedentitytype AS ENUM ('ar', 'ap', 'expense');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN 
            CREATE TYPE filestatus AS ENUM ('uploading', 'processing', 'completed', 'failed', 'reprocessing');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    
    op.execute("""
        DO $$ BEGIN 
            CREATE TYPE classificationstatus AS ENUM ('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$;
    """)
    
    # Check if bank_files table exists
    if not table_exists('bank_files'):
        # Create bank_files table with all columns including AI fields
        op.create_table(
            'bank_files',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('original_filename', sa.String(500), nullable=False),
            sa.Column('storage_path', sa.String(1000), nullable=False),
            sa.Column('file_size', sa.Integer(), nullable=True),
            sa.Column('content_type', sa.String(100), nullable=True),
            sa.Column('file_hash', sa.String(64), nullable=True),
            sa.Column('status', postgresql.ENUM('uploading', 'processing', 'completed', 'failed', 'reprocessing', name='filestatus', create_type=False), nullable=False, server_default='uploading'),
            sa.Column('error_message', sa.Text(), nullable=True),
            sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('parsed_rows', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('skipped_rows', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('bank_name', sa.String(100), nullable=True),
            sa.Column('account_number_last4', sa.String(4), nullable=True),
            sa.Column('statement_start_date', sa.DateTime(), nullable=True),
            sa.Column('statement_end_date', sa.DateTime(), nullable=True),
            sa.Column('uploaded_by', sa.String(255), nullable=True),
            # AI Classification fields
            sa.Column('classification_status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', name='classificationstatus', create_type=False), nullable=False, server_default='PENDING'),
            sa.Column('classification_progress', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_classification_error', sa.Text(), nullable=True),
            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_bank_files_status', 'bank_files', ['status'])
    else:
        # Table exists, just add missing AI columns
        if not column_exists('bank_files', 'classification_status'):
            op.add_column('bank_files', sa.Column('classification_status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', name='classificationstatus', create_type=False), nullable=False, server_default='PENDING'))
        if not column_exists('bank_files', 'classification_progress'):
            op.add_column('bank_files', sa.Column('classification_progress', sa.Integer(), nullable=False, server_default='0'))
        if not column_exists('bank_files', 'last_classification_error'):
            op.add_column('bank_files', sa.Column('last_classification_error', sa.Text(), nullable=True))
    
    # Check if bank_transactions table exists
    if not table_exists('bank_transactions'):
        # Create bank_transactions table with all columns including AI fields
        op.create_table(
            'bank_transactions',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('bank_file_id', sa.Integer(), nullable=False),
            sa.Column('external_id', sa.String(255), nullable=True),
            sa.Column('date', sa.DateTime(), nullable=False),
            sa.Column('post_date', sa.DateTime(), nullable=True),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('amount', sa.Float(), nullable=False),
            sa.Column('type', postgresql.ENUM('credit', 'debit', name='transactiontype', create_type=False), nullable=False),
            sa.Column('balance', sa.Float(), nullable=True),
            sa.Column('category', sa.String(100), nullable=True),
            sa.Column('memo', sa.Text(), nullable=True),
            sa.Column('check_number', sa.String(50), nullable=True),
            sa.Column('status', postgresql.ENUM('pending', 'matched', 'reviewed', 'cleared', 'reconciled', 'excluded', name='transactionstatus', create_type=False), nullable=False, server_default='pending'),
            # AI Classification fields
            sa.Column('ai_category', sa.String(100), nullable=True),
            sa.Column('ai_subcategory', sa.String(200), nullable=True),
            sa.Column('ai_confidence', sa.Float(), nullable=True),
            sa.Column('ai_ledger_hint', sa.String(50), nullable=True),
            sa.Column('classification_status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', name='classificationstatus', create_type=False), nullable=False, server_default='PENDING'),
            # Raw data
            sa.Column('raw_data', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('row_number', sa.Integer(), nullable=True),
            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['bank_file_id'], ['bank_files.id'], name='bank_transactions_bank_file_id_fkey')
        )
        op.create_index('ix_bank_transactions_bank_file_id', 'bank_transactions', ['bank_file_id'])
        op.create_index('ix_bank_transactions_external_id', 'bank_transactions', ['external_id'])
        op.create_index('ix_bank_transactions_date', 'bank_transactions', ['date'])
        op.create_index('ix_bank_transactions_status', 'bank_transactions', ['status'])
        op.create_index('idx_bank_transactions_classification_status', 'bank_transactions', ['classification_status'])
    else:
        # Table exists, just add missing AI columns
        if not column_exists('bank_transactions', 'ai_category'):
            op.add_column('bank_transactions', sa.Column('ai_category', sa.String(100), nullable=True))
        if not column_exists('bank_transactions', 'ai_subcategory'):
            op.add_column('bank_transactions', sa.Column('ai_subcategory', sa.String(200), nullable=True))
        if not column_exists('bank_transactions', 'ai_confidence'):
            op.add_column('bank_transactions', sa.Column('ai_confidence', sa.Float(), nullable=True))
        if not column_exists('bank_transactions', 'ai_ledger_hint'):
            op.add_column('bank_transactions', sa.Column('ai_ledger_hint', sa.String(50), nullable=True))
        if not column_exists('bank_transactions', 'classification_status'):
            op.add_column('bank_transactions', sa.Column('classification_status', postgresql.ENUM('PENDING', 'IN_PROGRESS', 'DONE', 'FAILED', name='classificationstatus', create_type=False), nullable=False, server_default='PENDING'))
            op.create_index('idx_bank_transactions_classification_status', 'bank_transactions', ['classification_status'])
    
    # Check if bank_matches table exists
    if not table_exists('bank_matches'):
        # Create bank_matches table
        op.create_table(
            'bank_matches',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('bank_transaction_id', sa.Integer(), nullable=False),
            sa.Column('matched_type', postgresql.ENUM('ar', 'ap', 'expense', name='matchedentitytype', create_type=False), nullable=False),
            sa.Column('matched_id', sa.Integer(), nullable=False),
            sa.Column('matched_reference', sa.String(100), nullable=True),
            sa.Column('matched_name', sa.String(255), nullable=True),
            sa.Column('match_confidence', sa.Float(), nullable=True),
            sa.Column('is_auto_matched', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('matched_by', sa.String(255), nullable=True),
            sa.Column('matched_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('notes', sa.Text(), nullable=True),
            # Timestamps
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_transactions.id'], name='bank_matches_bank_transaction_id_fkey'),
            sa.UniqueConstraint('bank_transaction_id', name='bank_matches_bank_transaction_id_key')
        )
        op.create_index('ix_bank_matches_bank_transaction_id', 'bank_matches', ['bank_transaction_id'])
    
    # Check if bank_feed_audit_logs table exists
    if not table_exists('bank_feed_audit_logs'):
        # Create bank_feed_audit_logs table
        op.create_table(
            'bank_feed_audit_logs',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('action', sa.String(100), nullable=False),
            sa.Column('details', postgresql.JSON(astext_type=sa.Text()), nullable=True),
            sa.Column('actor_type', sa.String(50), nullable=False),
            sa.Column('actor_id', sa.String(255), nullable=True),
            sa.Column('actor_name', sa.String(255), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column('bank_file_id', sa.Integer(), nullable=True),
            sa.Column('bank_transaction_id', sa.Integer(), nullable=True),
            sa.Column('bank_match_id', sa.Integer(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['bank_file_id'], ['bank_files.id'], name='bank_feed_audit_logs_bank_file_id_fkey'),
            sa.ForeignKeyConstraint(['bank_transaction_id'], ['bank_transactions.id'], name='bank_feed_audit_logs_bank_transaction_id_fkey'),
            sa.ForeignKeyConstraint(['bank_match_id'], ['bank_matches.id'], name='bank_feed_audit_logs_bank_match_id_fkey')
        )
        op.create_index('ix_bank_feed_audit_logs_action', 'bank_feed_audit_logs', ['action'])
        op.create_index('ix_bank_feed_audit_logs_timestamp', 'bank_feed_audit_logs', ['timestamp'])
        op.create_index('ix_bank_feed_audit_logs_bank_file_id', 'bank_feed_audit_logs', ['bank_file_id'])
        op.create_index('ix_bank_feed_audit_logs_bank_transaction_id', 'bank_feed_audit_logs', ['bank_transaction_id'])


def downgrade() -> None:
    # Remove index if it exists
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'bank_transactions' in inspector.get_table_names():
        indexes = [idx['name'] for idx in inspector.get_indexes('bank_transactions')]
        if 'idx_bank_transactions_classification_status' in indexes:
            op.drop_index('idx_bank_transactions_classification_status', table_name='bank_transactions')
    
    # Remove AI columns from bank_transactions if table exists
    if table_exists('bank_transactions'):
        if column_exists('bank_transactions', 'classification_status'):
            op.drop_column('bank_transactions', 'classification_status')
        if column_exists('bank_transactions', 'ai_ledger_hint'):
            op.drop_column('bank_transactions', 'ai_ledger_hint')
        if column_exists('bank_transactions', 'ai_confidence'):
            op.drop_column('bank_transactions', 'ai_confidence')
        if column_exists('bank_transactions', 'ai_subcategory'):
            op.drop_column('bank_transactions', 'ai_subcategory')
        if column_exists('bank_transactions', 'ai_category'):
            op.drop_column('bank_transactions', 'ai_category')
    
    # Remove AI columns from bank_files if table exists
    if table_exists('bank_files'):
        if column_exists('bank_files', 'last_classification_error'):
            op.drop_column('bank_files', 'last_classification_error')
        if column_exists('bank_files', 'classification_progress'):
            op.drop_column('bank_files', 'classification_progress')
        if column_exists('bank_files', 'classification_status'):
            op.drop_column('bank_files', 'classification_status')
    
    # Note: We don't drop the enum types or tables as they might be used elsewhere
    # The downgrade only removes the AI classification columns
