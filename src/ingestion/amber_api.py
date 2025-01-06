import os
import requests
import csv
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load API token from .env file
load_dotenv("config/.env")
API_TOKEN = os.getenv("AMBER_API_TOKEN")

BASE_URL = "https://api.amber.com.au/v1"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}"}

# File paths
PRICES_CSV = "prices_data.csv"
USAGE_CSV = "usage_data.csv"

# Fetch site ID
def get_site_id():
    response = requests.get(f"{BASE_URL}/sites", headers=HEADERS)
    response.raise_for_status()
    sites = response.json()
    return sites[0]["id"] if sites else None

# Fetch data from a given endpoint
def fetch_data(endpoint, start_date, end_date, params=None):
    params = params or {}
    params.update({"startDate": start_date, "endDate": end_date})
    response = requests.get(endpoint, headers=HEADERS, params=params)
    response.raise_for_status()
    return response.json()

# Write data to CSV
def write_to_csv(file_path, data, fieldnames):
    file_exists = os.path.isfile(file_path)
    with open(file_path, mode="a", newline="") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for record in data:
            writer.writerow(record)

# Fetch historical data
def fetch_historical_data(site_id, start_date, csv_path, endpoint, fieldnames):
    current_date = start_date
    today = datetime.utcnow().date()

    while current_date < today:
        next_date = current_date + timedelta(days=7)
        end_date = min(next_date, today)
        print(f"Fetching data from {current_date} to {end_date}...")

        data = fetch_data(endpoint, current_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        write_to_csv(csv_path, data, fieldnames)

        current_date = next_date

# Main function
if __name__ == "__main__":
    site_id = get_site_id()
    if not site_id:
        print("No site ID found.")
        exit(1)

    print(f"Using Site ID: {site_id}")

    # Historical Prices
    print("\nFetching Prices Data...")
    prices_endpoint = f"{BASE_URL}/sites/{site_id}/prices"
    prices_fields = [
        "type", "date", "duration", "startTime", "endTime", "nemTime",
        "perKwh", "renewables", "spotPerKwh", "channelType", "spikeStatus",
        "tariffInformation", "descriptor"
    ]
    fetch_historical_data(site_id, datetime(2024, 6, 24).date(), PRICES_CSV, prices_endpoint, prices_fields)

    # Historical Usage
    print("\nFetching Usage Data...")
    usage_endpoint = f"{BASE_URL}/sites/{site_id}/usage"
    usage_fields = [
        "type", "duration", "date", "startTime", "endTime", "nemTime", 
        "quality", "kwh", "perKwh", "channelType", "channelIdentifier", 
        "cost", "renewables", "spotPerKwh", "spikeStatus", "tariffInformation", "descriptor"
    ]
    fetch_historical_data(site_id, datetime(2024, 6, 24).date(), USAGE_CSV, usage_endpoint, usage_fields)

    print("\nData fetching completed!")
    print(f"Prices data saved to {PRICES_CSV}")
    print(f"Usage data saved to {USAGE_CSV}")