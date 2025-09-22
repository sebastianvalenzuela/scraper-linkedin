import requests
import time
from bs4 import BeautifulSoup
from sqlalchemy import create_engine, Column, String, DateTime, Text, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os
from datetime import datetime, timedelta
import re
import logging
from sqlalchemy.dialects.postgresql import insert
from models import ScraperLinkedinJob, ScraperLinkedinJobDetail, Base, SessionLocal, engine, ScraperEvent
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import logging
from datetime import datetime
from logging_loki import LokiHandler

# Configurar logging
class CustomFormatter(logging.Formatter):
    def format(self, record):
        record.message = record.getMessage()
        return f"{self.formatTime(record, self.datefmt)} - {record.levelname} - [linkedin-extract] - {record.message}"

class LokiJsonFormatter(logging.Formatter):
    def format(self, record):
        # Create structured log entry for Loki
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "linkedin-scraper"
        }
        
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
            
        return json.dumps(log_entry)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Logging configuration
LOG_EVENTS_ENABLED = os.getenv('LOG_EVENTS_ENABLED', 'true').lower() == 'true'
LOKI_ENABLED = os.getenv('LOKI_ENABLED', 'true').lower() == 'true'

# Configure logging for Loki
def setup_loki_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Remove existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Get Loki configuration from environment
    loki_url = os.getenv('GRAFANA_LOKI_URL')
    loki_username = os.getenv('GRAFANA_USER_ID')
    loki_password = os.getenv('GRAFANA_API_KEY')
    
    if loki_url:
        # Configure Loki handler for Grafana Cloud
        # Grafana Cloud uses API key authentication
        headers = {}
        if loki_password:  # API key
            headers['Authorization'] = f'Bearer {loki_password}'
        
        loki_handler = LokiHandler(
            url=loki_url,
            tags={"service": "linkedin-scraper"},
            auth=(loki_username or "user", loki_password),  # API key as password
            version="1",
        )
        logger.addHandler(loki_handler)
        
        # Also keep console output for local debugging
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(LokiJsonFormatter())
        logger.addHandler(console_handler)
    else:
        # Fallback to console-only logging
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(LokiJsonFormatter())
        logger.addHandler(console_handler)
        logger.warning("LOKI_URL not configured, using console logging only")
    
    return logger

# Custom logging functions for metrics
def log_metric(logger, event_type, **kwargs):
    """Log structured metrics for Loki"""
    extra_fields = {
        "event_type": event_type,
        "scraper_phase": kwargs.get("phase", "unknown")
    }
    extra_fields.update(kwargs)
    
    logger.info(f"Metric: {event_type}", extra={"extra_fields": extra_fields})

def log_db_event(event_type, records_count=0, execution_time=0.0, status="success", error_message=None):
    """Log a simple scraper event to the database"""
    try:
        session = SessionLocal()
        event = ScraperEvent()
        event.process_name = "linkedin-scraper-chile"  # TODO: Make configurable
        event.event_type = event_type
        event.records_count = records_count
        event.status = status
        event.execution_time_seconds = execution_time
        event.error_message = error_message
        session.add(event)
        session.commit()
        print(f"📝 DB Event logged: {event_type} ({records_count} records)")
    except Exception as e:
        print(f"❌ Failed to log DB event {event_type}: {e}")
    finally:
        session.close()

setup_loki_logging()

# Cargar variables de entorno
logger.info("Cargando variables de entorno...")
load_dotenv()

# Configuración
MAX_CONSECUTIVE_404 = int(os.getenv('LINKEDIN_MAX_CONSECUTIVE_404', 10))
MAX_RETRIES = int(os.getenv('LINKEDIN_MAX_RETRIES', 5))
RETRY_DELAY = int(os.getenv('LINKEDIN_RETRY_DELAY', 5))
MAX_THREADS = int(os.getenv('LINKEDIN_MAX_THREADS', 2))  # Configurable, default 2

def parse_posted_time(posted_time_text, current_time=None):
    if not posted_time_text:
        return None

    if current_time is None:
        current_time = datetime.now()

    # Patron para extraer número y unidad (minutes, hours, days)
    pattern = r"(\d+)\s+(minute|minutes|hour|hours|day|days|week|weeks|month|months)\s+ago"
    match = re.search(pattern, posted_time_text)

    if not match:
        return None

    quantity = int(match.group(1))
    unit = match.group(2)

    if unit == "minute" or unit == "minutes":
        delta = timedelta(minutes=quantity)
    elif unit == "hour" or unit == "hours":
        delta = timedelta(hours=quantity)
    elif unit == "day" or unit == "days":
        delta = timedelta(days=quantity)
    elif unit == "week" or unit == "weeks":
        delta = timedelta(weeks=quantity)
    elif unit == "month" or unit == "months":
        # Aproximadamente 30 días por mes
        delta = timedelta(days=quantity * 30)
    else:
        return None

    published_date = current_time - delta
    return published_date


def get_pending_jobs():
    logger.info("Obteniendo trabajos pendientes...")
    with SessionLocal() as session:
        jobs = session.query(ScraperLinkedinJob).filter(ScraperLinkedinJob.status == 'pending').all()
        return [(job.id, job.country) for job in jobs]


def process_job(job_id, country):
    # Create a new session for this job/thread
    session = SessionLocal()
    try:
        url = f"https://www.linkedin.com/jobs/api/jobPosting/{job_id}"
        logger.info(f"Procesando ID {job_id}...")

        for attempt in range(MAX_RETRIES):
            logger.info(f"Intento {attempt + 1} de {MAX_RETRIES} para el ID {job_id}.")
            try:
                response = requests.get(url, timeout=10)
                response.raise_for_status()

                soup = BeautifulSoup(response.content, 'html.parser')

                # Extraer información
                job_title = soup.find('h2', class_='top-card-layout__title')
                job_title = job_title.text.strip() if job_title else None

                company_name = soup.find('a', class_='topcard__org-name-link')
                company_name = company_name.text.strip() if company_name else None

                location_detail = soup.find('span', class_='topcard__flavor topcard__flavor--bullet')
                location_detail = location_detail.text.strip() if location_detail else None

                posted_time = soup.find('span', class_='posted-time-ago__text')
                posted_time = posted_time.text.strip() if posted_time else None

                # Calcular la fecha de publicación
                current_time = datetime.now()
                published_date = parse_posted_time(posted_time, current_time)

                applicant_count = soup.find('span', class_='num-applicants__caption')
                applicant_count = applicant_count.text.strip() if applicant_count else None

                description_div = soup.find('div',
                                            class_="show-more-less-html__markup show-more-less-html__markup--clamp-after-5 relative overflow-hidden")
                job_description = description_div.get_text(separator=' ', strip=True) if description_div else None

                job_criteria_items = soup.find_all('li', class_='description__job-criteria-item')
                seniority_level = job_criteria_items[0].find('span',
                                                             class_='description__job-criteria-text').text.strip() if len(
                    job_criteria_items) > 0 else None
                employment_type = job_criteria_items[1].find('span',
                                                             class_='description__job-criteria-text').text.strip() if len(
                    job_criteria_items) > 1 else None
                job_function = job_criteria_items[2].find('span',
                                                          class_='description__job-criteria-text').text.strip() if len(
                    job_criteria_items) > 2 else None
                industries = job_criteria_items[3].find('span',
                                                        class_='description__job-criteria-text').text.strip() if len(
                    job_criteria_items) > 3 else None

                extract_date = datetime.now()
                country_code = country

                # Get country from the original job
                original_job = session.query(ScraperLinkedinJob).filter(ScraperLinkedinJob.id == job_id).first()
                job_country = original_job.country if original_job else country
                
                # Crear o actualizar detalle del trabajo
                job_detail = ScraperLinkedinJobDetail(
                    id=job_id,
                    job_title=job_title,
                    company_name=company_name,
                    location=location_detail,
                    country=job_country,  
                    posted_time=posted_time,
                    published_date=published_date,
                    applicant_count=applicant_count,
                    job_description=job_description,
                    seniority_level=seniority_level,
                    employment_type=employment_type,
                    job_function=job_function,
                    industries=industries,
                    url=url,
                    extract_date=extract_date,
                    status='completed'
                )

                session.merge(job_detail)  # Insert or update
                
                # Update job status to completed
                job = session.query(ScraperLinkedinJob).filter(ScraperLinkedinJob.id == job_id).first()
                if job:
                    job.status = 'completed'
                
                session.commit()
                logger.info(f"Datos guardados exitosamente para el ID {job_id}.")
                return True

            except requests.exceptions.RequestException as e:
                if hasattr(response, 'status_code') and response.status_code == 404:
                    logger.warning(f"Recibido un 404 para el ID {job_id}.")
                    job = session.query(ScraperLinkedinJob).filter(ScraperLinkedinJob.id == job_id).first()
                    if job:
                        job.status = 'failed'
                    session.commit()
                    return False
                logger.error(f"Error en la solicitud para el ID {job_id}: {e}")
                if attempt < MAX_RETRIES - 1:
                    logger.info(f"Reintentando en {RETRY_DELAY} segundos...")
                    time.sleep(RETRY_DELAY)
            except Exception as e:
                logger.error(f"Error inesperado procesando el ID {job_id}: {e}")
                job = session.query(ScraperLinkedinJob).filter(ScraperLinkedinJob.id == job_id).first()
                if job:
                    job.status = 'failed'
                session.commit()
                return False

        logger.error(f"La solicitud para el ID {job_id} falló después de varios intentos.")
        job = session.query(ScraperLinkedinJob).filter(ScraperLinkedinJob.id == job_id).first()
        if job:
            job.status = 'failed'
        session.commit()
        return False
    finally:
        session.close()


def main():
    logger.info("Iniciando proceso de extracción de trabajos...")
    log_db_event('scraper_start')

    pending_jobs = get_pending_jobs()
    logger.info(f"Encontrados {len(pending_jobs)} trabajos pendientes.")
    
    logger.info("Extracción iniciada")

    if not pending_jobs:
        logger.info("No hay trabajos pendientes. Terminando.")
        log_db_event('scraper_end', status='success', records_count=0)
        return

    consecutive_404s = 0
    
    logger.info(f"Iniciando procesamiento con {MAX_THREADS} threads")
    start_time = time.time()
    
    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = {executor.submit(process_job, job_id, country): (job_id, country) for job_id, country in pending_jobs}
        
        processed_count = 0
        saved_count = 0
        failed_count = 0
        
        for future in as_completed(futures):
            job_id, country = futures[future]
            try:
                result = future.result()
                processed_count += 1
                
                if result:
                    saved_count += 1
                else:
                    failed_count += 1
                
                # Log progress every 10 jobs
                if processed_count % 10 == 0:
                    elapsed = time.time() - start_time
                    logger.info(f"Procesados {processed_count}/{len(pending_jobs)} jobs en {elapsed:.1f}s")
                
            except Exception as e:
                logger.error(f"Error en thread para ID {job_id}: {e}")
                consecutive_404s += 1

    total_time = time.time() - start_time
    
    logger.info("Extracción completada")
    logger.info(f"Procesamiento completado en {total_time:.1f}s. Jobs procesados: {processed_count}")
    log_db_event('scraper_end', status='success', records_count=processed_count, execution_time=total_time)


if __name__ == "__main__":
    main()
