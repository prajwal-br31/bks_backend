"""Initial email ingestion tables

Revision ID: 001_initial
Revises: 
Create Date: 2025-01-01
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Email messages table
    op.create_table(
        'email_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('message_id', sa.String(512), nullable=False),
        sa.Column('thread_id', sa.String(256), nullable=True),
        sa.Column('from_address', sa.String(320), nullable=False),
        sa.Column('to_addresses', sa.Text(), nullable=True),
        sa.Column('cc_addresses', sa.Text(), nullable=True),
        sa.Column('subject', sa.Text(), nullable=True),
        sa.Column('received_date', sa.DateTime(), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('source_folder', sa.String(256), nullable=True),
        sa.Column('source_provider', sa.String(50), nullable=False),
        sa.Column('processing_status', sa.Enum(
            'pending', 'processing', 'completed', 'failed', 'needs_review', 'virus_detected',
            name='processingstatus'
        ), nullable=False, server_default='pending'),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('message_id')
    )
    op.create_index('ix_email_messages_message_id', 'email_messages', ['message_id'])
    op.create_index('ix_email_messages_received_date', 'email_messages', ['received_date'])
    op.create_index('ix_email_messages_from_address', 'email_messages', ['from_address'])

    # Tags table
    op.create_table(
        'tags',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('color', sa.String(7), nullable=False, server_default='#6366f1'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )

    # Email documents table
    op.create_table(
        'email_documents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email_id', sa.Integer(), nullable=False),
        sa.Column('original_filename', sa.String(512), nullable=False),
        sa.Column('content_type', sa.String(128), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_hash', sa.String(64), nullable=False),
        sa.Column('storage_path', sa.String(1024), nullable=False),
        sa.Column('storage_bucket', sa.String(256), nullable=False),
        sa.Column('document_type', sa.Enum(
            'invoice', 'receipt', 'statement', 'unknown',
            name='documenttype'
        ), nullable=False, server_default='unknown'),
        sa.Column('destination', sa.Enum(
            'account_payable', 'account_receivable', 'needs_review',
            name='documentdestination'
        ), nullable=False, server_default='needs_review'),
        sa.Column('classification_confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('parsed_fields', sa.JSON(), nullable=True),
        sa.Column('ocr_text', sa.Text(), nullable=True),
        sa.Column('ocr_provider', sa.String(50), nullable=True),
        sa.Column('ocr_confidence', sa.Float(), nullable=True),
        sa.Column('processing_status', sa.Enum(
            'pending', 'processing', 'completed', 'failed', 'needs_review', 'virus_detected',
            name='processingstatus', create_type=False
        ), nullable=False, server_default='pending'),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('virus_scanned', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('virus_scan_result', sa.String(256), nullable=True),
        sa.Column('virus_scanned_at', sa.DateTime(), nullable=True),
        sa.Column('is_draft', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('posted_at', sa.DateTime(), nullable=True),
        sa.Column('posted_by', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['email_id'], ['email_messages.id'], ondelete='CASCADE')
    )
    op.create_index('ix_email_documents_document_type', 'email_documents', ['document_type'])
    op.create_index('ix_email_documents_processing_status', 'email_documents', ['processing_status'])
    op.create_index('ix_email_documents_file_hash', 'email_documents', ['file_hash'])

    # Document tags (many-to-many)
    op.create_table(
        'document_tags',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('added_by', sa.String(256), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_id'], ['email_documents.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tags.id'], ondelete='CASCADE')
    )
    op.create_index('ix_document_tags_document_id', 'document_tags', ['document_id'])
    op.create_index('ix_document_tags_tag_id', 'document_tags', ['tag_id'])

    # Audit logs
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('event_type', sa.String(100), nullable=False),
        sa.Column('event_data', sa.JSON(), nullable=True),
        sa.Column('actor', sa.String(256), nullable=True),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.String(512), nullable=True),
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_id'], ['email_documents.id'], ondelete='SET NULL')
    )
    op.create_index('ix_audit_logs_document_id', 'audit_logs', ['document_id'])
    op.create_index('ix_audit_logs_event_type', 'audit_logs', ['event_type'])
    op.create_index('ix_audit_logs_timestamp', 'audit_logs', ['timestamp'])

    # Notifications
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('document_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(256), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('notification_type', sa.String(50), nullable=False),
        sa.Column('severity', sa.String(20), nullable=False, server_default='info'),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_dismissed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('actions', sa.JSON(), nullable=True),
        sa.Column('reference_id', sa.String(100), nullable=True),
        sa.Column('amount', sa.String(50), nullable=True),
        sa.Column('source', sa.String(256), nullable=True),
        sa.Column('user_id', sa.String(256), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['document_id'], ['email_documents.id'], ondelete='SET NULL')
    )
    op.create_index('ix_notifications_user_id', 'notifications', ['user_id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])


def downgrade() -> None:
    op.drop_table('notifications')
    op.drop_table('audit_logs')
    op.drop_table('document_tags')
    op.drop_table('email_documents')
    op.drop_table('tags')
    op.drop_table('email_messages')
    
    # Drop enums
    op.execute("DROP TYPE IF EXISTS documentdestination")
    op.execute("DROP TYPE IF EXISTS documenttype")
    op.execute("DROP TYPE IF EXISTS processingstatus")

