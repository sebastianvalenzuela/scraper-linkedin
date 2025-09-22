#!/bin/bash

# LinkedIn Scraper Cron Script
# Runs discovery (main.py) and extraction (job_extractor.py) sequentially

echo "$(date): Starting LinkedIn scraper..."

# Run discovery phase
echo "$(date): Running discovery phase (main.py)..."
python main.py
MAIN_EXIT_CODE=$?

if [ $MAIN_EXIT_CODE -ne 0 ]; then
    echo "$(date): ERROR - Discovery phase failed with exit code $MAIN_EXIT_CODE"
    exit $MAIN_EXIT_CODE
fi

echo "$(date): Discovery phase completed successfully."

# Run extraction phase
echo "$(date): Running extraction phase (job_extractor.py)..."
python job_extractor.py
EXTRACTOR_EXIT_CODE=$?

if [ $EXTRACTOR_EXIT_CODE -ne 0 ]; then
    echo "$(date): ERROR - Extraction phase failed with exit code $EXTRACTOR_EXIT_CODE"
    exit $EXTRACTOR_EXIT_CODE
fi

echo "$(date): Extraction phase completed successfully."
echo "$(date): LinkedIn scraper completed successfully."

exit 0
