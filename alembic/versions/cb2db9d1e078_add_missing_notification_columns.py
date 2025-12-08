"""add_missing_notification_columns

Revision ID: cb2db9d1e078
Revises: 003_bank_feed_ai
Create Date: 2025-12-08 02:47:58.899218
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision: str = 'cb2db9d1e078'
down_revision: Union[str, None] = '003_bank_feed_ai'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(table_name: str, column_name: str) -> bool:
    """Check if a column exists in a table."""
    bind = op.get_bind()
    inspector = inspect(bind)
    if table_name not in inspector.get_table_names():
        return False
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def upgrade() -> None:
    # Add missing columns to notifications table
    if not column_exists('notifications', 'reference_type'):
        op.add_column('notifications', sa.Column('reference_type', sa.String(50), nullable=True))
    
    if not column_exists('notifications', 'reference_code'):
        op.add_column('notifications', sa.Column('reference_code', sa.String(100), nullable=True))
    
    if not column_exists('notifications', 'destination'):
        op.add_column('notifications', sa.Column('destination', sa.String(100), nullable=True))
    
    if not column_exists('notifications', 'link'):
        op.add_column('notifications', sa.Column('link', sa.String(500), nullable=True))
    
    if not column_exists('notifications', 'status'):
        # Add status column
        op.add_column('notifications', sa.Column('status', sa.String(20), nullable=True))
        
        # Migrate data from is_read to status
        # If is_read exists, migrate: is_read=True -> status='read', is_read=False -> status='unread'
        if column_exists('notifications', 'is_read'):
            op.execute("""
                UPDATE notifications 
                SET status = CASE 
                    WHEN is_read = true THEN 'read'
                    ELSE 'unread'
                END
                WHERE status IS NULL
            """)
        
        # Set default for new rows
        op.alter_column('notifications', 'status', 
                       server_default='unread',
                       nullable=False)
        
        # Create index on status
        op.create_index('ix_notifications_status', 'notifications', ['status'])
    
    # Handle dismissed column (rename is_dismissed to dismissed if needed)
    if column_exists('notifications', 'is_dismissed') and not column_exists('notifications', 'dismissed'):
        # Copy data from is_dismissed to dismissed
        op.add_column('notifications', sa.Column('dismissed', sa.Boolean(), nullable=True))
        op.execute("""
            UPDATE notifications 
            SET dismissed = is_dismissed
            WHERE dismissed IS NULL
        """)
        op.alter_column('notifications', 'dismissed',
                       server_default='false',
                       nullable=False)
        # Note: We keep is_dismissed for now to avoid breaking existing code
        # It can be dropped in a future migration if needed
    
    # Handle reference_id type change (String to Integer)
    # This is tricky - we'll keep both for now and let the application handle the conversion
    # If reference_id exists as String, we'll add a new integer column for new data
    # For now, we'll just ensure the column exists and can be nullable
    if column_exists('notifications', 'reference_id'):
        # Check if it's already Integer type
        bind = op.get_bind()
        inspector = inspect(bind)
        columns = inspector.get_columns('notifications')
        ref_id_col = next((col for col in columns if col['name'] == 'reference_id'), None)
        if ref_id_col and str(ref_id_col['type']) != 'INTEGER':
            # It's a String type, we need to handle this carefully
            # For now, we'll add a new column reference_id_int and let the app migrate
            # But actually, let's just make sure the model can handle both
            # The safest approach is to keep reference_id as nullable String for now
            pass
    
    # Add index on notification_type if it doesn't exist
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes('notifications')]
    if 'ix_notifications_notification_type' not in indexes:
        op.create_index('ix_notifications_notification_type', 'notifications', ['notification_type'])


def downgrade() -> None:
    # Remove indexes
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes('notifications')]
    
    if 'ix_notifications_status' in indexes:
        op.drop_index('ix_notifications_status', table_name='notifications')
    if 'ix_notifications_notification_type' in indexes:
        op.drop_index('ix_notifications_notification_type', table_name='notifications')
    
    # Remove columns
    if column_exists('notifications', 'status'):
        op.drop_column('notifications', 'status')
    if column_exists('notifications', 'link'):
        op.drop_column('notifications', 'link')
    if column_exists('notifications', 'destination'):
        op.drop_column('notifications', 'destination')
    if column_exists('notifications', 'reference_code'):
        op.drop_column('notifications', 'reference_code')
    if column_exists('notifications', 'reference_type'):
        op.drop_column('notifications', 'reference_type')
    
    # Note: We don't remove dismissed column as it might have data
    # If needed, it can be removed in a separate migration
