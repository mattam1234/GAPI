"""
Content moderation service for managing reports and enforcing community guidelines.
"""
import re
import json
from datetime import datetime, timedelta
from sqlalchemy import desc, or_
from database import UserReport, ModerationLog, ProfanityFilter, Chat_Message


class ModerationService:
    """Handles content moderation, reporting, and filtering."""

    def __init__(self, db_module):
        self._db = db_module
        self._profanity_cache = None

    def report_user_content(self, db, reporter: str, report_type: str, 
                            reason: str, description: str = None, 
                            reported_username: str = None, resource_id: str = None):
        """Create a report for user-generated content or user behavior."""
        try:
            report = UserReport(
                reporter_username=reporter,
                report_type=report_type,  # 'user', 'chat', 'review'
                reason=reason,
                description=description,
                reported_username=reported_username,
                resource_id=resource_id,
                resource_type=report_type,
            )
            db.add(report)
            db.commit()
            return report.id
        except Exception:
            db.rollback()
            return None

    def get_pending_reports(self, db, limit: int = 50, offset: int = 0):
        """Get pending reports for review by moderators."""
        try:
            reports = db.query(UserReport).filter(
                UserReport.status == 'pending'
            ).order_by(
                desc(UserReport.priority),
                desc(UserReport.created_at)
            ).limit(limit).offset(offset).all()

            total = db.query(UserReport).filter(
                UserReport.status == 'pending'
            ).count()

            return {
                'reports': [self._report_to_dict(r) for r in reports],
                'total': total,
            }
        except Exception:
            return {'reports': [], 'total': 0}

    def take_moderation_action(self, db, report_id: int, moderator: str, 
                               action: str, notes: str = None, duration: int = None):
        """Record a moderation action on a report."""
        try:
            report = db.query(UserReport).filter(UserReport.id == report_id).first()
            if not report:
                return False

            # Create moderation log
            mod_log = ModerationLog(
                moderator_username=moderator,
                action=action,
                target_username=report.reported_username,
                target_content_id=report.resource_id,
                reason=report.reason,
                duration=duration,
                notes=notes,
            )
            if duration:
                mod_log.expires_at = datetime.utcnow() + timedelta(minutes=duration)

            # Update report status
            report.status = 'resolved' if action != 'dismiss' else 'dismissed'
            report.resolved_by = moderator
            report.resolved_at = datetime.utcnow()

            db.add(mod_log)
            db.commit()
            return True
        except Exception:
            db.rollback()
            return False

    def check_profanity(self, db, text: str):
        """Check text for profanity and return flagged words."""
        try:
            if not self._profanity_cache:
                self._load_profanity_cache(db)

            flagged = []
            for word_data in self._profanity_cache:
                word = word_data['word']
                pattern = r'\b' + re.escape(word) + r'\b'
                if re.search(pattern, text, re.IGNORECASE):
                    flagged.append({
                        'word': word,
                        'severity': word_data['severity'],
                        'action': word_data['action'],
                    })

            return {
                'has_profanity': len(flagged) > 0,
                'flagged_words': flagged,
                'should_filter': any(f['action'] != 'flag' for f in flagged),
            }
        except Exception:
            return {'has_profanity': False, 'flagged_words': []}

    def add_profanity_word(self, db, word: str, severity: int = 1, 
                           auto_action: str = 'flag', added_by: str = None):
        """Add a word to the profanity filter."""
        try:
            existing = db.query(ProfanityFilter).filter(
                ProfanityFilter.word == word.lower()
            ).first()

            if existing:
                existing.severity = severity
                existing.auto_action = auto_action
            else:
                pf = ProfanityFilter(
                    word=word.lower(),
                    severity=severity,
                    auto_action=auto_action,
                    added_by=added_by,
                )
                db.add(pf)

            db.commit()
            self._profanity_cache = None  # Reset cache
            return True
        except Exception:
            db.rollback()
            return False

    def remove_profanity_word(self, db, word: str):
        """Remove a word from the profanity filter."""
        try:
            db.query(ProfanityFilter).filter(
                ProfanityFilter.word == word.lower()
            ).delete()
            db.commit()
            self._profanity_cache = None
            return True
        except Exception:
            db.rollback()
            return False

    def get_profanity_filter(self, db, limit: int = 100):
        """Get current profanity filter word list."""
        try:
            words = db.query(ProfanityFilter).filter(
                ProfanityFilter.enabled == True
            ).limit(limit).all()

            return [
                {
                    'id': w.id,
                    'word': w.word,
                    'severity': w.severity,
                    'action': w.auto_action,
                }
                for w in words
            ]
        except Exception:
            return []

    def get_moderation_logs(self, db, username: str = None, limit: int = 50):
        """Get moderation action history."""
        try:
            query = db.query(ModerationLog)
            if username:
                query = query.filter(ModerationLog.target_username == username)

            logs = query.order_by(desc(ModerationLog.timestamp)).limit(limit).all()
            return [self._mod_log_to_dict(log) for log in logs]
        except Exception:
            return []

    def get_user_violations(self, db, username: str):
        """Get moderation history for a specific user."""
        try:
            actions = db.query(UserReport).filter(
                UserReport.reported_username == username,
                UserReport.status == 'resolved',
            ).all()

            logs = db.query(ModerationLog).filter(
                ModerationLog.target_username == username
            ).all()

            return {
                'reports': [self._report_to_dict(r) for r in actions],
                'actions': [self._mod_log_to_dict(l) for l in logs],
            }
        except Exception:
            return {'reports': [], 'actions': []}

    def is_user_banned(self, db, username: str):
        """Check if user is currently banned."""
        try:
            ban = db.query(ModerationLog).filter(
                ModerationLog.target_username == username,
                ModerationLog.action == 'ban',
                or_(
                    ModerationLog.expires_at == None,
                    ModerationLog.expires_at > datetime.utcnow(),
                )
            ).first()
            return ban is not None
        except Exception:
            return False

    def is_user_muted(self, db, username: str):
        """Check if user is currently muted."""
        try:
            mute = db.query(ModerationLog).filter(
                ModerationLog.target_username == username,
                ModerationLog.action == 'mute',
                or_(
                    ModerationLog.expires_at == None,
                    ModerationLog.expires_at > datetime.utcnow(),
                )
            ).first()
            return mute is not None
        except Exception:
            return False

    # Private helpers

    def _load_profanity_cache(self, db):
        """Load profanity filter words into cache."""
        try:
            words = db.query(ProfanityFilter).filter(
                ProfanityFilter.enabled == True
            ).all()
            self._profanity_cache = [
                {
                    'word': w.word,
                    'severity': w.severity,
                    'action': w.auto_action,
                }
                for w in words
            ]
        except Exception:
            self._profanity_cache = []

    @staticmethod
    def _report_to_dict(report):
        """Convert UserReport ORM to dict."""
        return {
            'id': report.id,
            'reporter': report.reporter_username,
            'reported_user': report.reported_username,
            'report_type': report.report_type,
            'resource_id': report.resource_id,
            'reason': report.reason,
            'description': report.description,
            'status': report.status,
            'priority': report.priority,
            'created_at': report.created_at.isoformat() if report.created_at else None,
            'resolved_by': report.resolved_by,
        }

    @staticmethod
    def _mod_log_to_dict(log):
        """Convert ModerationLog ORM to dict."""
        return {
            'id': log.id,
            'moderator': log.moderator_username,
            'action': log.action,
            'target': log.target_username,
            'reason': log.reason,
            'duration_minutes': log.duration,
            'notes': log.notes,
            'timestamp': log.timestamp.isoformat() if log.timestamp else None,
            'expires_at': log.expires_at.isoformat() if log.expires_at else None,
        }
