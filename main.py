import requests
from dotenv import load_dotenv
import os
import re
from typing import List, Tuple, Any
import time
import threading
import logging
from models import ScraperLinkedinJob, SessionLocal, ScraperEvent
from datetime import datetime, timezone
import json
import logging
from logging_loki import LokiHandler
from sqlalchemy.dialects.postgresql import insert

load_dotenv()

stop_event = threading.Event()

# Create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class Counter:
    def __init__(self, value=0):
        self.value = value

#carga variables de entonrno
SOURCE_NAME = os.getenv('SOURCE_NAME', 'Linkedin')
DEFAULT_MAX_WORKERS = int(os.getenv('LINKEDIN_MAX_WORKERS', 4))
DEFAULT_MAX_CONSECUTIVE_404 = int(os.getenv('LINKEDIN_MAX_CONSECUTIVE_404', 10))
DEFAULT_MAX_CONSECUTIVE_429 = int(os.getenv('LINKEDIN_MAX_CONSECUTIVE_429', 5))
DEFAULT_MAX_CONSECUTIVE_EMPTY = int(os.getenv('LINKEDIN_MAX_CONSECUTIVE_EMPTY', 10))
DEFAULT_MAX_RANGE = int(os.getenv('LINKEDIN_MAX_RANGE', 1000))
DEFAULT_STEPS = int(os.getenv('LINKEDIN_STEPS', 25))
DEFAULT_RETRY_DELAY = int(os.getenv('LINKEDIN_RETRY_DELAY', 5))
DEFAULT_MAX_RETRIES = int(os.getenv('LINKEDIN_MAX_RETRIES', 3))
DEFAULT_F_TPR_VALUE = os.getenv('LINKEDIN_F_TPR_VALUE', 'r86400')
DEFAULT_DB_BATCH_SIZE = int(os.getenv('LINKEDIN_DB_BATCH_SIZE', 100))

LOCATION = os.getenv('LINKEDIN_LOCATION', 'Chile')

# Logging configuration
LOG_EVENTS_ENABLED = os.getenv('LOG_EVENTS_ENABLED', 'true').lower() == 'true'
LOKI_ENABLED = os.getenv('LOKI_ENABLED', 'true').lower() == 'true'
LOG_DISCOVERY_DETAILS = os.getenv('LOG_DISCOVERY_DETAILS', 'false').lower() == 'true'

shared_lock = threading.Lock()
no_id_counter = Counter(0)

total_workers = 0

class LokiJsonFormatter(logging.Formatter):
    def format(self, record):
        # Create structured log entry for Loki
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": "linkedin-scraper"
        }
        
        # Add extra fields if present
        if hasattr(record, 'extra_fields'):
            log_entry.update(record.extra_fields)
            
        return json.dumps(log_entry)

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

def log_event(event_type, **kwargs):
    """Log structured events for Loki"""
    extra_fields = {
        "event_type": event_type
    }
    extra_fields.update(kwargs)
    
    logger.info(f"Event: {event_type}", extra={"extra_fields": extra_fields})

def log_db_event(event_type, records_count=0, execution_time=0.0, status="success", error_message=None):
    """Log a simple scraper event to the database"""
    if not LOG_EVENTS_ENABLED:
        return
        
    try:
        session = SessionLocal()
        # Create event object and set attributes
        event = ScraperEvent()
        event.process_name = f"linkedin-scraper-{LOCATION.lower()}"
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

def handle_request_with_retry(
    url: str,
    consecutive_404_counter: Any,
    consecutive_429_counter: Any,
    consecutive_empty_counter: Any,
    no_id_counter: Any,
    stop_event: Any,
    shared_lock: Any,
    max_consecutive_404: int,
    max_consecutive_429: int,
    max_consecutive_empty: int,
    total_workers: int,
    retry_delay: int,
    max_retries: int,
    worker_logger
) -> Tuple[bool, str]:
    """
    Maneja una solicitud HTTP con reintentos y manejo de errores específicos.
    Retorna (éxito: bool, html_content: str).
    Si falla definitivamente, retorna (False, "").
    """
    for attempt in range(max_retries):
        if stop_event.is_set():
            worker_logger.info("Evento de parada detectado, terminando.")
            return False, ""

        try:
            worker_logger.debug(f"Intento {attempt + 1}/{max_retries} para URL: {url}")
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}, timeout=20)

            # Manejo de 429 (Too Many Requests)
            if response.status_code == 429:
                with shared_lock:
                    consecutive_429_counter.value += 1
                    current_429 = consecutive_429_counter.value
                worker_logger.warning(f"Error 429. Contador: {current_429}/{max_consecutive_429}")
                if current_429 >= max_consecutive_429:
                    worker_logger.error("Límite de errores 429 alcanzado. Señalando parada.")
                    stop_event.set()
                    return False, ""
                sleep_time = retry_delay * (2 ** attempt)
                worker_logger.info(f"Esperando {sleep_time}s debido a 429...")
                time.sleep(sleep_time)
                continue

            # Manejo de 404 (Not Found)
            elif response.status_code == 404:
                with shared_lock:
                    consecutive_404_counter.value += 1
                    current_404 = consecutive_404_counter.value
                worker_logger.warning(f"Error 404. Contador: {current_404}/{max_consecutive_404}")
                if current_404 >= max_consecutive_404:
                    worker_logger.error("Límite de errores 404 alcanzado. Señalando parada.")
                    stop_event.set()
                return False, ""

            response.raise_for_status()

            # Reset de contadores al éxito
            with shared_lock:
                consecutive_429_counter.value = 0
                consecutive_404_counter.value = 0

            # Manejo de contenido vacío
            html_content = response.text.strip()
            if not html_content or html_content == "<!DOCTYPE html><!---->":
                with shared_lock:
                    consecutive_empty_counter.value += 1
                    current_empty = consecutive_empty_counter.value
                worker_logger.warning(f"HTML vacío. Contador: {current_empty}/{max_consecutive_empty}. HTML: {html_content[:200]}...")
                if current_empty >= max_consecutive_empty:
                    worker_logger.error("Límite de HTMLs vacíos alcanzado. Señalando parada.")
                    stop_event.set()
                return False, ""

            with shared_lock:
                consecutive_empty_counter.value = 0

            return True, html_content

        except requests.exceptions.RequestException as e:
            worker_logger.warning(f"Error de red/HTTP en intento {attempt + 1}: {e}")
            if attempt >= max_retries - 1:
                worker_logger.error(f"Máximos reintentos alcanzados para {url}. Fallando.")
                return False, ""
            time.sleep(retry_delay * (attempt + 1))

        except Exception as e:
            worker_logger.error(f"Error inesperado: {e}", exc_info=True)
            return False, ""

    worker_logger.error(f"Solicitud falló definitivamente después de {max_retries} intentos para {url}.")
    return False, ""




start = 0

while True:
    url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?location={LOCATION}&f_TPR=r86400&pageNum=0&start={start}"

    # Usar la función auxiliar para la solicitud
    success, html_content = handle_request_with_retry(
        url=url,
        consecutive_404_counter=Counter(0),
        consecutive_429_counter=Counter(0),
        consecutive_empty_counter=Counter(0),
        no_id_counter=no_id_counter,
        stop_event=stop_event,
        shared_lock=shared_lock,
        max_consecutive_404=DEFAULT_MAX_CONSECUTIVE_404,
        max_consecutive_429=DEFAULT_MAX_CONSECUTIVE_429,
        max_consecutive_empty=DEFAULT_MAX_CONSECUTIVE_EMPTY,
        total_workers=total_workers,
        retry_delay=6,
        max_retries=5,
        worker_logger=logger
    )

    # Extracción de IDs
    ids_str_list = re.findall(r'data-entity-urn="urn:li:jobPosting:(\d+)"', html_content)

    if not ids_str_list:
        log_event("no_ids_found")
        log_db_event("no_ids_found")
        print("No se encontraron más IDs. Terminando.")
        break

    # Log discovery iteration
    log_event("discovery_iteration", records_count=len(ids_str_list))
    if LOG_DISCOVERY_DETAILS:
        log_db_event("discovery_iteration", records_count=len(ids_str_list))
        print(f"Encontrados {len(ids_str_list)} IDs en esta iteración y guardados en la base de datos.")

    # Bulk insert de los IDs encontrados
    with SessionLocal() as session:
        jobs_to_insert = [
            {"id": id_str, "country": LOCATION, "status": "pending"} 
            for id_str in ids_str_list
        ]
        stmt = insert(ScraperLinkedinJob).values(jobs_to_insert).on_conflict_do_nothing(index_elements=['id'])
        session.execute(stmt)
        session.commit()

    log_metric(logger, "ids_inserted", count=len(ids_str_list))

    start += len(ids_str_list)

log_event("discovery_completed", records_count=start)
log_db_event("discovery_completed", records_count=start)
print(f"Proceso completado. Start final: {start}")
log_db_event("scraping_completed", records_count=start)