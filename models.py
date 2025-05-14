import os
from datetime import datetime
from sqlalchemy import Column, Integer, BigInteger, String, Float, DateTime, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy import create_engine

# Создаем базовый класс для моделей
Base = declarative_base()

class User(Base):
    """Модель пользователя"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    is_premium = Column(Boolean, default=False)
    test_used = Column(Boolean, default=False)
    
    # Отношения
    subscriptions = relationship("Subscription", back_populates="user", cascade="all, delete-orphan")
    access_keys = relationship("AccessKey", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<User(telegram_id={self.telegram_id}, username='{self.username}')>"

class Subscription(Base):
    """Модель подписки"""
    __tablename__ = 'subscriptions'
    
    id = Column(Integer, primary_key=True)
    subscription_id = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    plan_id = Column(String(50), nullable=False)
    status = Column(String(20), default='active')
    created_at = Column(DateTime, default=datetime.now)
    expires_at = Column(DateTime, nullable=True)
    price_paid = Column(Float, default=0.0)
    
    # Отношения
    user = relationship("User", back_populates="subscriptions")
    access_keys = relationship("AccessKey", back_populates="subscription", cascade="all, delete-orphan")
    
    def __repr__(self):
        return f"<Subscription(subscription_id='{self.subscription_id}', status='{self.status}')>"

class AccessKey(Base):
    """Модель ключа доступа"""
    __tablename__ = 'access_keys'
    
    id = Column(Integer, primary_key=True)
    key_id = Column(String(255), unique=True, nullable=False)
    name = Column(String(255), nullable=True)
    access_url = Column(String(1024), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subscription_id = Column(Integer, ForeignKey('subscriptions.id'), nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    deleted = Column(Boolean, default=False)
    
    # Отношения
    user = relationship("User", back_populates="access_keys")
    subscription = relationship("Subscription", back_populates="access_keys")
    
    def __repr__(self):
        return f"<AccessKey(key_id='{self.key_id}', name='{self.name}')>"

class Payment(Base):
    """Модель платежа"""
    __tablename__ = 'payments'
    
    id = Column(Integer, primary_key=True)
    payment_id = Column(String(255), unique=True, nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    subscription_id = Column(String(255), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String(10), default='RUB')
    status = Column(String(20), default='pending')
    created_at = Column(DateTime, default=datetime.now)
    completed_at = Column(DateTime, nullable=True)
    
    # Отношения
    user = relationship("User", back_populates="payments")
    
    def __repr__(self):
        return f"<Payment(payment_id='{self.payment_id}', status='{self.status}')>"

# Инициализация базы данных
def init_db():
    """Инициализация базы данных"""
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL environment variable is not set")
    
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    return engine

# Создание сессии
def get_session():
    """Создание сессии для работы с базой данных"""
    engine = init_db()
    Session = sessionmaker(bind=engine)
    return Session()