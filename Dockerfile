FROM python:3.13-slim

# Install only basic system dependencies (no Chrome/Selenium needed)
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY main.py .
COPY job_extractor.py .
COPY models.py .

# Copy and make executable the scraper wrapper script
COPY run_scraper.sh .
RUN chmod +x run_scraper.sh

# Run the scraper wrapper
CMD ["/app/run_scraper.sh"]
