import requests
import os
from dotenv import load_dotenv
import json

# Load API token from .env file
load_dotenv("config/.env")
API_TOKEN = os.getenv("AMBER_API_TOKEN")

BASE_URL = "https://api.amber.com.au/v1"

# Define headers
headers = {
    "Authorization": f"Bearer {API_TOKEN}"
}

def test_api_endpoint(endpoint, params=None):
    """
    Test a given API endpoint and return its response structure.
    """
    try:
        response = requests.get(endpoint, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            print(f"Endpoint {endpoint} returned {len(data)} records.")
            if data:
                print("Sample Record Structure:")
                print(json.dumps(data[0], indent=2))  # Print the structure of the first record
            else:
                print("No data available for this endpoint.")
        elif response.status_code == 429:
            print(f"Rate limit reached for endpoint {endpoint}.")
        else:
            print(f"Error fetching data from {endpoint}: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Unexpected error: {e}")

if __name__ == "__main__":
    # Test sites endpoint
    print("Testing Sites Endpoint...")
    sites_endpoint = f"{BASE_URL}/sites"
    response_sites = requests.get(sites_endpoint, headers=headers)

    if response_sites.status_code == 200:
        sites = response_sites.json()
        site_id = sites[0]['id'] if sites else None
        print(f"Found Site ID: {site_id}")

        # Test prices endpoint
        if site_id:
            print("\nTesting Prices Endpoint...")
            prices_endpoint = f"{BASE_URL}/sites/{site_id}/prices"
            test_api_endpoint(prices_endpoint, params={"startDate": "2024-11-01", "endDate": "2024-11-07"})

            # Test usage endpoint
            print("\nTesting Usage Endpoint...")
            usage_endpoint = f"{BASE_URL}/sites/{site_id}/usage"
            test_api_endpoint(usage_endpoint, params={"startDate": "2024-11-01", "endDate": "2024-11-07"})

            # Test forecast endpoint
            print("\nTesting Forecast Endpoint...")
            forecast_endpoint = f"{BASE_URL}/sites/{site_id}/prices/current"
            test_api_endpoint(forecast_endpoint)
    else:
        print(f"Error fetching sites: {response_sites.status_code} - {response_sites.text}")