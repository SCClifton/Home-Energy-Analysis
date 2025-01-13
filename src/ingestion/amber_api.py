import os
import requests
import csv
import logging
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# ----------------------------------------------------
#  Logging Configuration
# ----------------------------------------------------
LOG_FILE = "logs/amber_ingestion.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# Load API token from .env file
load_dotenv("config/.env")
API_TOKEN = os.getenv("AMBER_API_TOKEN")

BASE_URL = "https://api.amber.com.au/v1"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

# File paths
PRICES_CSV = "prices_data.csv"
USAGE_CSV = "usage_data.csv"


def get_site_id():
    """Fetch the site ID from the Amber API. Returns the first site ID found."""
    response = requests.get(f"{BASE_URL}/sites", headers=HEADERS)
    response.raise_for_status()
    sites = response.json()
    return sites[0]["id"] if sites else None


def fetch_data(endpoint, start_date, end_date, params=None):
    """Generic helper to fetch data from a given endpoint, handling date ranges and params."""
    params = params or {}
    params.update({"startDate": start_date, "endDate": end_date})
    response = requests.get(endpoint, headers=HEADERS, params=params)
    response.raise_for_status()
    return response.json()


def write_to_csv(file_path, data, fieldnames):
    """
    Appends data to a CSV file. If the file doesn't exist,
    writes headers first, then each record.
    """
    file_exists = os.path.isfile(file_path)
    with open(file_path, mode="a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for record in data:
            writer.writerow(record)


def get_last_date_in_csv(csv_path, date_column="date"):
    """
    Reads the CSV file and returns the most recent date (as a datetime.date object).
    Returns None if the file doesn't exist or is empty.
    """
    if not os.path.isfile(csv_path):
        return None  # File doesn't exist

    last_date = None
    with open(csv_path, "r", newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            raw_date = row.get(date_column)
            if raw_date:
                try:
                    parsed_date = datetime.strptime(raw_date, "%Y-%m-%dT%H:%M:%S.%fZ").date()
                    if not last_date or parsed_date > last_date:
                        last_date = parsed_date
                except ValueError:
                    continue  # Skip invalid dates

    return last_date


def fetch_historical_data(site_id, default_start_date, csv_path, endpoint, fieldnames):
    """
    Fetches historical data in 7-day increments, starting either from 'default_start_date'
    or from one day after the last date in the existing CSV. Writes to 'csv_path'.
    """
    # Check the most recent date in the CSV
    last_date = get_last_date_in_csv(csv_path, date_column="date")
    
    if last_date:
        current_date = last_date + timedelta(days=1)
        logging.info(f"Resuming from {current_date}, based on {csv_path}.")
    else:
        current_date = default_start_date
        logging.info(f"Starting from {current_date}, no prior data in {csv_path}.")

    today = datetime.now(timezone.utc).date()
    if current_date >= today:
        logging.info(f"No new data to fetch for {csv_path}. Already up to date.")
        return

    while current_date < today:
        next_date = current_date + timedelta(days=7)
        end_date = min(next_date, today)

        logging.info(f"Fetching data from {current_date} to {end_date}.")
        data = fetch_data(endpoint, current_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        write_to_csv(csv_path, data, fieldnames)

        current_date = next_date


def main():
    """Main workflow for fetching prices and usage data from Amber API."""
    logging.info("Starting amber_api ingestion process...")

    site_id = get_site_id()
    if not site_id:
        logging.error("No site ID found; exiting.")
        return

    logging.info(f"Using Site ID: {site_id}")

    # Historical Prices
    logging.info("Fetching Prices Data...")
    prices_endpoint = f"{BASE_URL}/sites/{site_id}/prices"
    prices_fields = [
        "type", "date", "duration", "startTime", "endTime", "nemTime",
        "perKwh", "renewables", "spotPerKwh", "channelType", "spikeStatus",
        "tariffInformation", "descriptor"
    ]
    fetch_historical_data(
        site_id,
        datetime(2024, 6, 24).date(),
        PRICES_CSV,
        prices_endpoint,
        prices_fields
    )

    # Historical Usage
    logging.info("Fetching Usage Data...")
    usage_endpoint = f"{BASE_URL}/sites/{site_id}/usage"
    usage_fields = [
        "type", "duration", "date", "startTime", "endTime", "nemTime",
        "quality", "kwh", "perKwh", "channelType", "channelIdentifier",
        "cost", "renewables", "spotPerKwh", "spikeStatus", 
        "tariffInformation", "descriptor"
    ]
    fetch_historical_data(
        site_id,
        datetime(2024, 6, 24).date(),
        USAGE_CSV,
        usage_endpoint,
        usage_fields
    )

    logging.info("Data fetching completed!")
    logging.info(f"Prices data saved to {PRICES_CSV}")
    logging.info(f"Usage data saved to {USAGE_CSV}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logging.exception("An error occurred during data ingestion.")
        exit(1)