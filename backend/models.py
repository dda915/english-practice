from sqlalchemy import Column, Integer, Float, Text, Boolean, Date, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    unit_number = Column(Float, nullable=False, default=0, index=True)
    number = Column(Integer, nullable=False, unique=True, index=True)
    japanese = Column(Text, nullable=False)
    english = Column(Text, nullable=False)

    answers = relationship("Answer", back_populates="question")


class Child(Base):
    __tablename__ = "children"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    stage = Column(Integer, nullable=False, default=1)
    access_code = Column(Text, nullable=True, unique=True)

    answers = relationship("Answer", back_populates="child")
    point_logs = relationship("PointLog", back_populates="child")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    answered_date = Column(DateTime, nullable=False)
    correct = Column(Boolean, nullable=False)

    child = relationship("Child", back_populates="answers")
    question = relationship("Question", back_populates="answers")


class PointLog(Base):
    __tablename__ = "point_logs"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, index=True)
    logged_date = Column(Date, nullable=False)
    amount = Column(Integer, nullable=False)
    description = Column(Text, nullable=False)

    child = relationship("Child", back_populates="point_logs")


class Setting(Base):
    __tablename__ = "settings"

    key = Column(Text, primary_key=True)
    value = Column(Text, nullable=False)


class ActiveSession(Base):
    __tablename__ = "active_sessions"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, unique=True, index=True)
    question_ids = Column(Text, nullable=False)  # JSON array of question IDs

    child = relationship("Child")


class GradingBatch(Base):
    __tablename__ = "grading_batches"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=True, index=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, index=True)
    created_at = Column(DateTime, nullable=False)
    model = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)


class Grading(Base):
    __tablename__ = "gradings"

    id = Column(Integer, primary_key=True)
    batch_id = Column(Integer, ForeignKey("grading_batches.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    ai_reading = Column(Text, nullable=False, default="")
    ai_correct = Column(Boolean, nullable=False, default=False)
    ai_comment = Column(Text, nullable=False, default="")
    feedback = Column(Text, nullable=True)  # 'accept' | 'question' | None
    status = Column(Text, nullable=False, default="pending")  # pending | confirmed | awaiting_parent | parent_confirmed
    final_correct = Column(Boolean, nullable=True)
    parent_comment = Column(Text, nullable=True)
    seen_by_child = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id = Column(Integer, primary_key=True)
    endpoint = Column(Text, nullable=False, unique=True, index=True)
    p256dh = Column(Text, nullable=False)
    auth = Column(Text, nullable=False)
    user_type = Column(Text, nullable=False)  # 'parent' | 'child'
    child_id = Column(Integer, ForeignKey("children.id"), nullable=True, index=True)
    created_at = Column(DateTime, nullable=False)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=True, index=True)
    sender = Column(Text, nullable=False)  # 'parent' | 'child'
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)
    read_by_parent = Column(Boolean, nullable=False, default=False)
    read_by_child = Column(Boolean, nullable=False, default=False)


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True)
    grading_id = Column(Integer, ForeignKey("gradings.id"), nullable=False, index=True)
    role = Column(Text, nullable=False)  # 'user' | 'assistant'
    content = Column(Text, nullable=False)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, nullable=False)


class SessionPhoto(Base):
    __tablename__ = "session_photos"

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, nullable=False, index=True)
    batch_id = Column(Integer, nullable=True, index=True)
    filename = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)


class ExchangeRequest(Base):
    __tablename__ = "exchange_requests"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, index=True)
    requested_date = Column(Date, nullable=False)
    exchange_type = Column(Text, nullable=False)  # "money" or "phone"
    points = Column(Integer, nullable=False)
    converted_value = Column(Integer, nullable=False)  # 円 or 分
    fulfilled = Column(Boolean, nullable=False, default=False)
    fulfilled_at = Column(DateTime, nullable=True)

    child = relationship("Child")


class EmailThread(Base):
    __tablename__ = "email_threads"

    id = Column(Integer, primary_key=True)
    thread_key = Column(Text, nullable=False, unique=True, index=True)
    message_id = Column(Text, nullable=False)  # 最初のメールの Message-ID


class ParentDevice(Base):
    __tablename__ = "parent_devices"

    id = Column(Integer, primary_key=True)
    device_id = Column(Text, nullable=False, unique=True, index=True)
    name = Column(Text, nullable=False)
    registered_at = Column(DateTime, nullable=False)
    last_seen_at = Column(DateTime, nullable=True)
