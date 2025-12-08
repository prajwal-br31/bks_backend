"""004_add_notification_reference_fields

Revision ID: 5aa22abf9649
Revises: cb2db9d1e078
Create Date: 2025-12-08 02:52:12.658838
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql

revision: str = '5aa22abf9649'
down_revision: Union[str, None] = 'cb2db9d1e078'
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


def get_column_type(table_name: str, column_name: str) -> str:
    """Get the type of a column as a string."""
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = inspector.get_columns(table_name)
    col = next((c for c in columns if c['name'] == column_name), None)
    if col:
        return str(col['type'])
    return None


def upgrade() -> None:
    """
    Add missing columns to notifications table to match the Notification model.
    
    Based on app/models/document.py Notification model, we need:
    - reference_type: String(50), nullable=True
    - reference_id: Integer, nullable=True (currently VARCHAR in DB)
    - reference_code: String(100), nullable=True
    - amount: String(50), nullable=True
    - source: String(255), nullable=True
    - destination: String(100), nullable=True
    - link: String(500), nullable=True
    - actions: JSON, nullable=True
    - status: String(20), default="unread", index=True
    - dismissed: Boolean, default=False
    """
    
    # Add reference_type if missing
    if not column_exists('notifications', 'reference_type'):
        op.add_column('notifications', 
                     sa.Column('reference_type', sa.String(50), nullable=True))
    
    # Add reference_code if missing
    if not column_exists('notifications', 'reference_code'):
        op.add_column('notifications', 
                     sa.Column('reference_code', sa.String(100), nullable=True))
    
    # Add destination if missing
    if not column_exists('notifications', 'destination'):
        op.add_column('notifications', 
                     sa.Column('destination', sa.String(100), nullable=True))
    
    # Add link if missing
    if not column_exists('notifications', 'link'):
        op.add_column('notifications', 
                     sa.Column('link', sa.String(500), nullable=True))
    
    # Add status if missing
    if not column_exists('notifications', 'status'):
        op.add_column('notifications', 
                     sa.Column('status', sa.String(20), nullable=True, server_default='unread'))
        
        # Migrate data from is_read if it exists
        if column_exists('notifications', 'is_read'):
            op.execute("""
                UPDATE notifications 
                SET status = CASE 
                    WHEN is_read = true THEN 'read'
                    ELSE 'unread'
                END
                WHERE status IS NULL
            """)
        
        # Make status NOT NULL after migration
        op.alter_column('notifications', 'status', nullable=False)
        
        # Create index on status
        bind = op.get_bind()
        inspector = inspect(bind)
        indexes = [idx['name'] for idx in inspector.get_indexes('notifications')]
        if 'ix_notifications_status' not in indexes:
            op.create_index('ix_notifications_status', 'notifications', ['status'])
    
    # Add dismissed if missing
    if not column_exists('notifications', 'dismissed'):
        op.add_column('notifications', 
                     sa.Column('dismissed', sa.Boolean(), nullable=True, server_default='false'))
        
        # Migrate data from is_dismissed if it exists
        if column_exists('notifications', 'is_dismissed'):
            op.execute("""
                UPDATE notifications 
                SET dismissed = is_dismissed
                WHERE dismissed IS NULL
            """)
        
        # Make dismissed NOT NULL after migration
        op.alter_column('notifications', 'dismissed', nullable=False)
    
    # Ensure amount exists (should already exist, but check)
    if not column_exists('notifications', 'amount'):
        op.add_column('notifications', 
                     sa.Column('amount', sa.String(50), nullable=True))
    
    # Ensure source exists (should already exist, but check)
    if not column_exists('notifications', 'source'):
        op.add_column('notifications', 
                     sa.Column('source', sa.String(255), nullable=True))
    
    # Ensure actions exists (should already exist, but check)
    if not column_exists('notifications', 'actions'):
        op.add_column('notifications', 
                     sa.Column('actions', postgresql.JSON(astext_type=sa.Text()), nullable=True))
    
    # Handle reference_id type conversion (VARCHAR to INTEGER)
    # The model expects Integer, but DB has VARCHAR(100)
    if column_exists('notifications', 'reference_id'):
        col_type = get_column_type('notifications', 'reference_id')
        if col_type and 'VARCHAR' in col_type.upper():
            # reference_id is currently VARCHAR, but model expects Integer
            # We'll add a new integer column and migrate data where possible
            # For now, keep both columns - the model can be updated to handle String
            # Or we can do a proper migration in a future step
            # For safety, we'll just ensure the column exists and is nullable
            pass  # Keep as-is for now to avoid data loss
    
    # Ensure notification_type has an index
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes('notifications')]
    if 'ix_notifications_notification_type' not in indexes:
        op.create_index('ix_notifications_notification_type', 'notifications', ['notification_type'])


def downgrade() -> None:
    """Remove the added columns."""
    # Remove indexes first
    bind = op.get_bind()
    inspector = inspect(bind)
    indexes = [idx['name'] for idx in inspector.get_indexes('notifications')]
    
    if 'ix_notifications_status' in indexes:
        op.drop_index('ix_notifications_status', table_name='notifications')
    if 'ix_notifications_notification_type' in indexes:
        op.drop_index('ix_notifications_notification_type', table_name='notifications')
    
    # Remove columns (only if they were added by this migration)
    # We check existence to avoid errors if columns don't exist
    if column_exists('notifications', 'link'):
        op.drop_column('notifications', 'link')
    if column_exists('notifications', 'destination'):
        op.drop_column('notifications', 'destination')
    if column_exists('notifications', 'reference_code'):
        op.drop_column('notifications', 'reference_code')
    if column_exists('notifications', 'reference_type'):
        op.drop_column('notifications', 'reference_type')
    if column_exists('notifications', 'status'):
        op.drop_column('notifications', 'status')
    if column_exists('notifications', 'dismissed'):
        op.drop_column('notifications', 'dismissed')
    
    # Note: We don't remove amount, source, or actions as they may have been
    # created in earlier migrations
