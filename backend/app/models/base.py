"""SQLAlchemy 声明基类。"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """所有数据表模型的基类。"""
