"""
Initialize Database with Default Data.

Creates tables and seeds default users/channels for development.

Usage:
    python scripts/init_db.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlmodel import Session

from backend.db.engine import engine, create_db_and_tables, DATA_ROOT
from backend.db.models import User, Channel, UserRole


def seed_users(session: Session) -> None:
    """Create default annotator accounts."""
    default_users = [
        {"username": "Chien", "role": UserRole.ADMIN},
        {"username": "May", "role": UserRole.ANNOTATOR},
        {"username": "VeeAnh", "role": UserRole.ANNOTATOR},
    ]
    
    for user_data in default_users:
        # Check if user exists
        existing = session.query(User).filter(User.username == user_data["username"]).first()
        if not existing:
            user = User(**user_data)
            session.add(user)
            print(f"  Created user: {user_data['username']} ({user_data['role']})")
        else:
            print(f"  User exists: {user_data['username']}")
    
    session.commit()


def seed_channels(session: Session) -> None:
    """Create default YouTube channels."""
    default_channels = [
        {"name": "Vietcetera", "url": "https://www.youtube.com/@Vietcetera"},
        {"name": "Unknown", "url": "https://www.youtube.com/unknown"},  # Fallback
    ]
    
    for channel_data in default_channels:
        existing = session.query(Channel).filter(Channel.url == channel_data["url"]).first()
        if not existing:
            channel = Channel(**channel_data)
            session.add(channel)
            print(f"  Created channel: {channel_data['name']}")
        else:
            print(f"  Channel exists: {channel_data['name']}")
    
    session.commit()


def create_directories() -> None:
    """Create data directories."""
    directories = [
        DATA_ROOT / "raw",      # Original downloads
        DATA_ROOT / "chunks",   # FFmpeg output
        DATA_ROOT / "export",   # Final dataset
        DATA_ROOT / "logs",     # Processing logs
    ]
    
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        print(f"  Created directory: {directory}")


def main() -> None:
    """Initialize database and seed data."""
    print("=" * 60)
    print("Vietnamese-English CS Speech Translation Pipeline")
    print("Database Initialization")
    print("=" * 60)
    
    print("\n[1/4] Creating directories...")
    create_directories()
    
    print("\n[2/4] Creating database tables...")
    create_db_and_tables()
    print("  Tables created successfully!")
    
    print("\n[3/4] Seeding users...")
    with Session(engine) as session:
        seed_users(session)
    
    print("\n[4/4] Seeding channels...")
    with Session(engine) as session:
        seed_channels(session)
    
    print("\n" + "=" * 60)
    print("✓ Database initialization complete!")
    print(f"  Data root: {DATA_ROOT.absolute()}")
    print("=" * 60)


if __name__ == "__main__":
    main()
