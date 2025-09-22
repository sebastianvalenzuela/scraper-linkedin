from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer, Float
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from datetime import datetime
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Database setup
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL not found in environment variables")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

class ScraperLinkedinJob(Base):
    __tablename__ = "scraper_linkedin_jobs"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)
    status: Mapped[str] = mapped_column(String, default="pending", server_default="pending")  # pending, completed, failed
    country: Mapped[str] = mapped_column(String, index=True)  
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ScraperLinkedinJobDetail(Base):
    __tablename__ = "scraper_linkedin_job_details"
    
    id: Mapped[str] = mapped_column(String, primary_key=True, index=True)  
    job_title: Mapped[str] = mapped_column(String, nullable=True)
    company_name: Mapped[str] = mapped_column(String, nullable=True)
    location: Mapped[str] = mapped_column(String, nullable=True)
    country: Mapped[str] = mapped_column(String, nullable=True)  
    posted_time: Mapped[str] = mapped_column(String, nullable=True)
    published_date: Mapped[datetime] = mapped_column(DateTime, nullable=True)
    applicant_count: Mapped[str] = mapped_column(String, nullable=True)
    job_description: Mapped[str] = mapped_column(Text, nullable=True)
    seniority_level: Mapped[str] = mapped_column(String, nullable=True)
    employment_type: Mapped[str] = mapped_column(String, nullable=True)
    job_function: Mapped[str] = mapped_column(String, nullable=True)
    industries: Mapped[str] = mapped_column(String, nullable=True)
    url: Mapped[str] = mapped_column(String, nullable=True)
    extract_date: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    status: Mapped[str] = mapped_column(String, default="processing")  

class ScraperEvent(Base):
    __tablename__ = "scraper_events"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    process_name = Column(String, index=True)  # e.g., "linkedin-scraper-chile"
    event_type = Column(String, index=True)  # discovery_started, discovery_completed, extraction_started, extraction_completed
    records_count = Column(Integer, default=0)  # jobs found/processed
    status = Column(String, default="success")  # success, failed, partial
    execution_time_seconds = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

# Create tables
Base.metadata.create_all(bind=engine)
