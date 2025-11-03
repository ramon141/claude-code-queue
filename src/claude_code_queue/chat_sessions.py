"""
Chat session management with SQLite database.
Maps custom chat names to real Claude Code session IDs.
"""

import sqlite3
import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime


class ChatSessionManager:
    """Manages mapping between chat names and Claude Code session IDs."""
    
    def __init__(self, storage_dir: str = "~/.claude-queue"):
        self.storage_dir = Path(storage_dir).expanduser()
        self.db_path = self.storage_dir / "chat_sessions.db"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._init_database()
    
    def _init_database(self):
        """Initialize the SQLite database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_name TEXT UNIQUE NOT NULL,
                    session_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    total_prompts INTEGER DEFAULT 0,
                    working_directory TEXT DEFAULT '.'
                )
            """)
            conn.commit()
    
    def save_chat_session(self, chat_name: str, session_id: str, working_directory: str = ".") -> bool:
        """Save a chat name to session ID mapping."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO chat_sessions 
                    (chat_name, session_id, working_directory, created_at, last_used)
                    VALUES (?, ?, ?, ?, ?)
                """, (chat_name, session_id, working_directory, datetime.now(), datetime.now()))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error saving chat session: {e}")
            return False
    
    def get_session_id(self, chat_name: str) -> Optional[str]:
        """Get the Claude Code session ID for a chat name."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    SELECT session_id FROM chat_sessions 
                    WHERE chat_name = ?
                """, (chat_name,))
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            print(f"Error getting session ID: {e}")
            return None
    
    def update_last_used(self, chat_name: str) -> bool:
        """Update the last used timestamp for a chat."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    UPDATE chat_sessions 
                    SET last_used = ?, total_prompts = total_prompts + 1
                    WHERE chat_name = ?
                """, (datetime.now(), chat_name))
                conn.commit()
            return True
        except Exception as e:
            print(f"Error updating last used: {e}")
            return False
    
    def list_chat_sessions(self) -> List[Dict[str, Any]]:
        """List all chat sessions."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM chat_sessions 
                    ORDER BY last_used DESC
                """)
                return [dict(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"Error listing chat sessions: {e}")
            return []
    
    def delete_chat_session(self, chat_name: str) -> bool:
        """Delete a chat session."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("""
                    DELETE FROM chat_sessions WHERE chat_name = ?
                """, (chat_name,))
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"Error deleting chat session: {e}")
            return False
    
    def chat_exists(self, chat_name: str) -> bool:
        """Check if a chat session exists."""
        return self.get_session_id(chat_name) is not None