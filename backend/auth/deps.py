"""
FastAPI Authentication Dependencies.

Uses "Honor System" auth - X-User-ID header contains the user ID.
Trusted team environment, no passwords required.
"""

from typing import Optional

from fastapi import Header, HTTPException, Depends
from sqlmodel import Session

from backend.db.engine import get_session
from backend.db.models import User


async def get_current_user(
    x_user_id: Optional[int] = Header(None, alias="X-User-ID"),
    session: Session = Depends(get_session)
) -> User:
    """
    Validate user ID from X-User-ID header.
    
    Args:
        x_user_id: User ID from header (required)
        session: Database session
        
    Returns:
        User object if valid
        
    Raises:
        HTTPException 401: If header missing or user not found
    """
    if x_user_id is None:
        raise HTTPException(
            status_code=401,
            detail="X-User-ID header required"
        )
    
    user = session.get(User, x_user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail=f"User with ID {x_user_id} not found"
        )
    
    return user


async def get_optional_user(
    x_user_id: Optional[int] = Header(None, alias="X-User-ID"),
    session: Session = Depends(get_session)
) -> Optional[User]:
    """
    Get user if X-User-ID header is provided, None otherwise.
    
    Use this for endpoints that work with or without auth.
    """
    if x_user_id is None:
        return None
    
    return session.get(User, x_user_id)
