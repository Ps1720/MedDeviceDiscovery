"""
Database Setup for Medical Device Discovery

Creates and manages the SQLite database for storing QR code records,
device information, and category groupings.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = 'qr_codes.db'


def create_connection():
    """Create a database connection to the SQLite database."""
    print(f"Connecting to database at: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Enable dict-like access to rows
    return conn


def create_tables(conn):
    """Create tables for storing QR code and category information."""
    
    c = conn.cursor()
    
    # Check if old schema exists and migrate if needed
    c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='qr_codes'")
    table_exists = c.fetchone()
    
    if table_exists:
        # Check if it's the old schema (missing 'device_id' or 'created_at')
        c.execute("PRAGMA table_info(qr_codes)")
        columns = [col[1] for col in c.fetchall()]
        print(f"Existing columns: {columns}")
        
        if 'device_id' not in columns or 'created_at' not in columns or 'category' not in columns:
            print("Detected old/incompatible schema. Dropping and recreating...")
            c.execute("DROP TABLE IF EXISTS qr_codes")
            c.execute("DROP TABLE IF EXISTS categories")
            conn.commit()
            print("Old tables dropped. Creating new schema...")
    
    # QR codes table with full device info
    sql_create_qr_codes_table = """
    CREATE TABLE IF NOT EXISTS qr_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL UNIQUE,
        device_name TEXT,
        manufacturer TEXT,
        category TEXT DEFAULT 'Uncategorized',
        device_type TEXT,
        qr_code_path TEXT NOT NULL,
        source TEXT DEFAULT 'manual',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_accessed TIMESTAMP
    );
    """
    
    # Categories table for organizing devices
    sql_create_categories_table = """
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        description TEXT,
        icon TEXT DEFAULT 'category',
        color TEXT DEFAULT 'primary',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    
    # Insert default categories
    default_categories = [
        ('Cardiovascular', 'Heart and vascular devices', 'favorite', 'red'),
        ('Orthopedic', 'Bone and joint devices', 'accessibility', 'blue'),
        ('Infusion & IV', 'Infusion pumps and IV equipment', 'water_drop', 'cyan'),
        ('Monitoring', 'Patient monitoring devices', 'monitor_heart', 'green'),
        ('Surgical', 'Surgical instruments and implants', 'healing', 'purple'),
        ('Respiratory', 'Breathing and airway devices', 'air', 'teal'),
        ('Imaging', 'Diagnostic imaging equipment', 'radiology', 'indigo'),
        ('Laboratory', 'Lab equipment and diagnostics', 'science', 'amber'),
        ('Uncategorized', 'Other medical devices', 'devices_other', 'slate'),
    ]
    
    try:
        c.execute(sql_create_qr_codes_table)
        c.execute(sql_create_categories_table)
        
        # Insert default categories if they don't exist
        for cat in default_categories:
            c.execute("""
                INSERT OR IGNORE INTO categories (name, description, icon, color) 
                VALUES (?, ?, ?, ?)
            """, cat)
        
        conn.commit()
        print("Database tables created successfully.")
        
    except sqlite3.Error as e:
        print(f"Database error: {e}")


def add_qr_code(conn, device_id: str, device_name: str = None, 
                manufacturer: str = None, category: str = 'Uncategorized',
                device_type: str = None, qr_code_path: str = None,
                source: str = 'manual') -> int:
    """
    Add a new QR code record to the database.
    
    Returns:
        The ID of the inserted record, or -1 if failed
    """
    try:
        c = conn.cursor()
        c.execute("""
            INSERT INTO qr_codes 
            (device_id, device_name, manufacturer, category, device_type, qr_code_path, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (device_id, device_name, manufacturer, category, device_type, 
              qr_code_path, source, datetime.now()))
        conn.commit()
        print(f"Added QR code record for device: {device_id}")
        return c.lastrowid
    except sqlite3.IntegrityError:
        print(f"QR code for {device_id} already exists in database.")
        return -1
    except sqlite3.Error as e:
        print(f"Error adding QR code: {e}")
        return -1


def get_qr_code(conn, device_id: str) -> dict:
    """Get a QR code record by device ID."""
    try:
        c = conn.cursor()
        c.execute("SELECT * FROM qr_codes WHERE device_id = ?", (device_id,))
        row = c.fetchone()
        if row:
            # Update last_accessed timestamp
            c.execute("""
                UPDATE qr_codes SET last_accessed = ? WHERE device_id = ?
            """, (datetime.now(), device_id))
            conn.commit()
            return dict(row)
        return None
    except sqlite3.Error as e:
        print(f"Error getting QR code: {e}")
        return None


def get_recent_qr_codes(conn, limit: int = 5) -> list:
    """Get the most recently created QR codes."""
    try:
        c = conn.cursor()
        c.execute("""
            SELECT * FROM qr_codes 
            ORDER BY created_at DESC 
            LIMIT ?
        """, (limit,))
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error as e:
        print(f"Error getting recent QR codes: {e}")
        return []


def get_qr_codes_by_category(conn, category: str = None) -> list:
    """Get QR codes filtered by category, or all if category is None."""
    try:
        c = conn.cursor()
        if category:
            c.execute("""
                SELECT * FROM qr_codes 
                WHERE category = ?
                ORDER BY created_at DESC
            """, (category,))
        else:
            c.execute("""
                SELECT * FROM qr_codes 
                ORDER BY category, created_at DESC
            """)
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error as e:
        print(f"Error getting QR codes by category: {e}")
        return []


def get_all_categories(conn) -> list:
    """Get all categories with device counts."""
    try:
        c = conn.cursor()
        c.execute("""
            SELECT c.*, COUNT(q.id) as device_count
            FROM categories c
            LEFT JOIN qr_codes q ON c.name = q.category
            GROUP BY c.id
            ORDER BY device_count DESC, c.name
        """)
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error as e:
        print(f"Error getting categories: {e}")
        return []


def search_qr_codes(conn, query: str) -> list:
    """Search QR codes by device ID, name, or manufacturer."""
    try:
        c = conn.cursor()
        search_term = f"%{query}%"
        c.execute("""
            SELECT * FROM qr_codes 
            WHERE device_id LIKE ? 
               OR device_name LIKE ? 
               OR manufacturer LIKE ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (search_term, search_term, search_term))
        return [dict(row) for row in c.fetchall()]
    except sqlite3.Error as e:
        print(f"Error searching QR codes: {e}")
        return []


def update_qr_code_category(conn, device_id: str, category: str) -> bool:
    """Update the category of a QR code."""
    try:
        c = conn.cursor()
        c.execute("""
            UPDATE qr_codes SET category = ? WHERE device_id = ?
        """, (category, device_id))
        conn.commit()
        return c.rowcount > 0
    except sqlite3.Error as e:
        print(f"Error updating category: {e}")
        return False


def delete_qr_code(conn, device_id: str) -> bool:
    """Delete a QR code record."""
    try:
        c = conn.cursor()
        c.execute("DELETE FROM qr_codes WHERE device_id = ?", (device_id,))
        conn.commit()
        return c.rowcount > 0
    except sqlite3.Error as e:
        print(f"Error deleting QR code: {e}")
        return False


def get_stats(conn) -> dict:
    """Get database statistics."""
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM qr_codes")
        total_qr = c.fetchone()[0]
        
        c.execute("SELECT COUNT(DISTINCT category) FROM qr_codes")
        categories_used = c.fetchone()[0]
        
        c.execute("""
            SELECT COUNT(*) FROM qr_codes 
            WHERE created_at > datetime('now', '-7 days')
        """)
        recent_week = c.fetchone()[0]
        
        return {
            'total_qr_codes': total_qr,
            'categories_used': categories_used,
            'created_this_week': recent_week
        }
    except sqlite3.Error as e:
        print(f"Error getting stats: {e}")
        return {}


def init_db():
    """Initialize the database with tables."""
    conn = create_connection()
    if conn is not None:
        create_tables(conn)
        conn.close()
        print("Database initialized successfully.")
    else:
        print("Error! Cannot create the database connection.")


if __name__ == '__main__':
    init_db()
    
    # Test the database
    conn = create_connection()
    
    # Test adding a QR code
    add_qr_code(
        conn,
        device_id='test_001',
        device_name='Test Device',
        manufacturer='Test Corp',
        category='Cardiovascular',
        qr_code_path='/static/qr_codes/test_001.png'
    )
    
    # Test getting recent codes
    recent = get_recent_qr_codes(conn)
    print(f"Recent QR codes: {recent}")
    
    # Test categories
    categories = get_all_categories(conn)
    print(f"Categories: {categories}")
    
    conn.close()