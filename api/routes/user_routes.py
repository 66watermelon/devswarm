from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging

from db.database import get_async_db
from models.user import User
from schemas.user import UserResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/{user_id}", response_model=UserResponse)
async def get_user_info(
        user_id: int,
        db: AsyncSession = Depends(get_async_db)
):
    """
    根据用户 ID 查询用户基本信息。
    """
    try:
        # 使用 SQLAlchemy 2.0 的 select() 语法
        stmt = select(User).where(User.id == user_id)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="用户不存在"
            )

        return user

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ 查询用户信息失败 (user_id={user_id}): {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="获取用户信息失败"
        )