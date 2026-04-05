from sqlalchemy import Column, Integer, Text, Boolean, Date, ForeignKey
from sqlalchemy.orm import relationship
from .database import Base


class Question(Base):
    __tablename__ = "questions"

    id = Column(Integer, primary_key=True)
    number = Column(Integer, nullable=False, unique=True, index=True)
    japanese = Column(Text, nullable=False)
    english = Column(Text, nullable=False)

    answers = relationship("Answer", back_populates="question")


class Child(Base):
    __tablename__ = "children"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)

    answers = relationship("Answer", back_populates="child")
    point_logs = relationship("PointLog", back_populates="child")


class Answer(Base):
    __tablename__ = "answers"

    id = Column(Integer, primary_key=True)
    child_id = Column(Integer, ForeignKey("children.id"), nullable=False, index=True)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False, index=True)
    answered_date = Column(Date, nullable=False)
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
