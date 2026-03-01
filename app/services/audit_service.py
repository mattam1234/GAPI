"""
Audit logging service for tracking all user actions and admin operations.
"""
import json
from datetime import datetime
from sqlalchemy import desc, and_, or_
from database import AuditLog


class AuditService:
    """Manages audit logging for compliance and security."""

    def __init__(self, db_module):
        self._db = db_module

    def log_action(self, db, username: str, action: str, resource_type: str = None,
                   resource_id: str = None, description: str = None, old_value: dict = None,
                   new_value: dict = None, ip_address: str = None, user_agent: str = None,
                   status: str = 'success', error_message: str = None):
        """Log an action for audit trail."""
        try:
            audit_log = AuditLog(
                username=username,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                description=description,
                old_value=json.dumps(old_value) if old_value else None,
                new_value=json.dumps(new_value) if new_value else None,
                ip_address=ip_address,
                user_agent=user_agent,
                status=status,
                error_message=error_message,
            )
            db.add(audit_log)
            db.commit()
            return True
        except Exception as e:
            db.rollback()
            return False

    def get_audit_logs(self, db, limit: int = 100, offset: int = 0, filters: dict = None):
        """Retrieve audit logs with optional filters."""
        try:
            query = db.query(AuditLog)

            if filters:
                if filters.get('username'):
                    query = query.filter(AuditLog.username == filters['username'])
                if filters.get('action'):
                    query = query.filter(AuditLog.action == filters['action'])
                if filters.get('resource_type'):
                    query = query.filter(AuditLog.resource_type == filters['resource_type'])
                if filters.get('status'):
                    query = query.filter(AuditLog.status == filters['status'])
                if filters.get('after_date'):
                    query = query.filter(AuditLog.timestamp >= filters['after_date'])
                if filters.get('before_date'):
                    query = query.filter(AuditLog.timestamp <= filters['before_date'])

            total = query.count()
            logs = query.order_by(desc(AuditLog.timestamp)).limit(limit).offset(offset).all()

            return {
                'logs': [self._log_to_dict(log) for log in logs],
                'total': total,
                'limit': limit,
                'offset': offset,
            }
        except Exception as e:
            return {'logs': [], 'total': 0, 'error': str(e)}

    def get_user_activity(self, db, username: str, limit: int = 50):
        """Get activity history for a specific user."""
        try:
            logs = db.query(AuditLog) \
                .filter(AuditLog.username == username) \
                .order_by(desc(AuditLog.timestamp)) \
                .limit(limit) \
                .all()
            return [self._log_to_dict(log) for log in logs]
        except Exception:
            return []

    def get_action_count(self, db, action: str, days: int = 7):
        """Get count of a specific action in the last N days."""
        try:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=days)
            count = db.query(AuditLog) \
                .filter(and_(
                    AuditLog.action == action,
                    AuditLog.timestamp >= cutoff,
                )) \
                .count()
            return count
        except Exception:
            return 0

    def get_admin_actions(self, db, username: str = None, limit: int = 100):
        """Get admin-specific actions (creating users, changing settings, etc.)."""
        try:
            admin_actions = ['create_user', 'delete_user', 'change_role', 'ban_user',
                            'save_settings', 'run_migration', 'toggle_plugin']
            query = db.query(AuditLog).filter(AuditLog.action.in_(admin_actions))

            if username:
                query = query.filter(AuditLog.username == username)

            logs = query.order_by(desc(AuditLog.timestamp)).limit(limit).all()
            return [self._log_to_dict(log) for log in logs]
        except Exception:
            return []

    def get_failed_logins(self, db, days: int = 1, limit: int = 50):
        """Get failed login attempts."""
        try:
            from datetime import timedelta
            cutoff = datetime.utcnow() - timedelta(days=days)
            logs = db.query(AuditLog) \
                .filter(and_(
                    AuditLog.action == 'login',
                    AuditLog.status == 'failure',
                    AuditLog.timestamp >= cutoff,
                )) \
                .order_by(desc(AuditLog.timestamp)) \
                .limit(limit) \
                .all()
            return [self._log_to_dict(log) for log in logs]
        except Exception:
            return []

    def export_audit_logs(self, db, filters: dict = None):
        """Export audit logs as CSV-formatted data."""
        try:
            logs = self.get_audit_logs(db, limit=10000, filters=filters)['logs']
            csv_lines = [
                'Timestamp,Username,Action,ResourceType,ResourceID,Status,IPAddress',
            ]
            for log in logs:
                csv_lines.append(
                    f"{log['timestamp']},{log['username']},{log['action']},"
                    f"{log['resource_type']},{log['resource_id']},{log['status']},"
                    f"{log['ip_address']}"
                )
            return '\n'.join(csv_lines)
        except Exception:
            return ''

    @staticmethod
    def _log_to_dict(log):
        """Convert AuditLog ORM object to dict."""
        return {
            'id': log.id,
            'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            'username': log.username,
            'action': log.action,
            'resource_type': log.resource_type,
            'resource_id': log.resource_id,
            'description': log.description,
            'old_value': json.loads(log.old_value) if log.old_value else None,
            'new_value': json.loads(log.new_value) if log.new_value else None,
            'ip_address': log.ip_address,
            'status': log.status,
            'error_message': log.error_message,
        }
