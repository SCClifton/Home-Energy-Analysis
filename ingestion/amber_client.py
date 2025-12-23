"""
Amber API Client

A clean, minimal client for interacting with the Amber Electric API.
Designed for use in a Raspberry Pi fridge dashboard application.
"""

import os
import logging
from datetime import datetime, date, timedelta
from typing import Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Configure logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler if not already configured
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(handler)


class AmberAPIError(Exception):
    """Custom exception for Amber API errors."""

    def __init__(self, message: str, status_code: Optional[int] = None, response_text: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_text = response_text

    def __str__(self):
        base_msg = super().__str__()
        if self.status_code:
            base_msg += f" (Status: {self.status_code})"
        if self.response_text:
            # Truncate long responses
            snippet = self.response_text[:200] + "..." if len(self.response_text) > 200 else self.response_text
            base_msg += f" | Response: {snippet}"
        return base_msg


class AmberClient:
    """
    Client for interacting with the Amber Electric API.
    
    Args:
        token: Amber API bearer token
        base_url: Base URL for the Amber API (default: https://api.amber.com.au/v1)
        timeout: Request timeout in seconds (default: 30)
    """

    def __init__(
        self,
        token: str,
        base_url: str = "https://api.amber.com.au/v1",
        timeout: int = 30,
    ):
        if not token:
            raise ValueError("Token cannot be empty")
        
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # Create a session with retry strategy
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.token}"})
        
        # Configure retry strategy for transient errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        logger.info(f"AmberClient initialized with base_url: {self.base_url}")

    def _request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Internal method to make HTTP requests with error handling.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (relative to base_url)
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            JSON response as a dictionary
            
        Raises:
            AmberAPIError: For API errors
            requests.exceptions.Timeout: For timeout errors
            requests.exceptions.RequestException: For other network errors
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        # Set default timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.timeout

        try:
            logger.debug(f"Making {method} request to {url}")
            response = self.session.request(method, url, **kwargs)
            
            # Handle HTTP errors
            if not response.ok:
                error_msg = f"API request failed: {method} {url}"
                logger.error(f"{error_msg} - Status: {response.status_code}")
                raise AmberAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_text=response.text,
                )
            
            return response.json()
            
        except requests.exceptions.Timeout as e:
            error_msg = f"Request timeout after {kwargs.get('timeout', self.timeout)}s: {method} {url}"
            logger.error(error_msg)
            raise requests.exceptions.Timeout(error_msg) from e
            
        except requests.exceptions.RequestException as e:
            error_msg = f"Network error: {method} {url}"
            logger.error(f"{error_msg} - {str(e)}")
            raise requests.exceptions.RequestException(error_msg) from e

    def get_sites(self) -> list[dict]:
        """
        Fetch all sites associated with the API token.
        
        Returns:
            List of site dictionaries
            
        Raises:
            AmberAPIError: If the API request fails
        """
        logger.info("Fetching sites...")
        try:
            sites = self._request("GET", "/sites")
            logger.info(f"Successfully fetched {len(sites)} site(s)")
            return sites
        except Exception as e:
            logger.error(f"Failed to fetch sites: {str(e)}")
            raise

    def get_current_prices(self, site_id: str) -> list[dict]:
        """
        Fetch current and upcoming prices for a site.
        
        Args:
            site_id: The site ID to fetch prices for
            
        Returns:
            List of price interval dictionaries
            
        Raises:
            AmberAPIError: If the API request fails
        """
        if not site_id:
            raise ValueError("site_id cannot be empty")
        
        logger.info(f"Fetching current prices for site {site_id}...")
        try:
            prices = self._request("GET", f"/sites/{site_id}/prices")
            logger.info(f"Successfully fetched {len(prices)} price interval(s)")
            return prices
        except Exception as e:
            logger.error(f"Failed to fetch prices for site {site_id}: {str(e)}")
            raise

    def get_prices_current(self, site_id: str) -> list[dict]:
        """
        Fetch current price for a site using the smallest available endpoint.
        
        Tries /sites/{site_id}/prices/current first. If that returns 404,
        falls back to /sites/{site_id}/prices?next=12&previous=0.
        
        Args:
            site_id: The site ID to fetch prices for
            
        Returns:
            List of price interval dictionaries (typically 1-13 intervals)
            
        Raises:
            AmberAPIError: If both endpoints fail
        """
        if not site_id:
            raise ValueError("site_id cannot be empty")
        
        logger.info(f"Fetching current price for site {site_id}...")
        
        # Try the /current endpoint first
        try:
            url = f"{self.base_url}/sites/{site_id}/prices/current"
            response = self.session.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                prices = response.json()
                # Ensure it's a list (API might return single dict or list)
                if isinstance(prices, dict):
                    prices = [prices]
                logger.info(f"Successfully fetched current price from /current endpoint")
                return prices
            elif response.status_code == 404:
                logger.info("/prices/current returned 404, falling back to /prices?next=12&previous=0")
            else:
                # For other errors, raise immediately
                error_msg = f"API request failed: GET {url}"
                logger.error(f"{error_msg} - Status: {response.status_code}")
                raise AmberAPIError(
                    error_msg,
                    status_code=response.status_code,
                    response_text=response.text,
                )
        except AmberAPIError:
            raise
        except requests.exceptions.RequestException as e:
            # If it's a network error (not 404), try fallback anyway
            logger.warning(f"Error accessing /prices/current: {e}, trying fallback")
        
        # Fallback to the minimal prices endpoint
        try:
            prices = self._request("GET", f"/sites/{site_id}/prices", params={"next": 12, "previous": 0})
            logger.info(f"Successfully fetched {len(prices)} price interval(s) from fallback endpoint")
            return prices
        except Exception as e:
            logger.error(f"Failed to fetch prices for site {site_id} from both endpoints: {str(e)}")
            raise

    def get_usage_recent(self, site_id: str, intervals: int = 1) -> list[dict]:
        """
        Fetch the most recent usage interval(s) for a site.
        
        Fetches today's usage data and returns the most recent interval(s).
        If today's data is not available, tries yesterday.
        
        Args:
            site_id: The site ID to fetch usage for
            intervals: Number of recent intervals to return (default: 1)
            
        Returns:
            List of usage interval dictionaries, sorted by time (most recent first).
            Each dict contains 'kwh', 'duration' (in minutes), 'startTime', 'endTime', etc.
            
        Raises:
            AmberAPIError: If the API request fails
        """
        if not site_id:
            raise ValueError("site_id cannot be empty")
        if intervals < 1:
            raise ValueError("intervals must be at least 1")
        
        logger.info(f"Fetching {intervals} most recent usage interval(s) for site {site_id}...")
        
        # Try today first, then yesterday if today has no data
        for days_ago in [0, 1]:
            target_date = date.today() - timedelta(days=days_ago)
            date_str = target_date.isoformat()
            
            try:
                usage_data = self._request(
                    "GET",
                    f"/sites/{site_id}/usage",
                    params={"startDate": date_str, "endDate": date_str}
                )
                
                if usage_data and len(usage_data) > 0:
                    # Sort by endTime (most recent first) and return the requested number
                    sorted_usage = sorted(
                        usage_data,
                        key=lambda x: x.get("endTime", ""),
                        reverse=True
                    )
                    result = sorted_usage[:intervals]
                    logger.info(f"Successfully fetched {len(result)} usage interval(s) from {date_str}")
                    return result
                else:
                    logger.debug(f"No usage data found for {date_str}")
                    
            except AmberAPIError as e:
                # If it's a 404 or other error, try next day
                if days_ago == 0:
                    logger.warning(f"Failed to fetch usage for {date_str}: {e}, trying yesterday")
                    continue
                else:
                    raise
        
        # If we get here, no data was found
        logger.warning(f"No usage data found for today or yesterday")
        return []

    def get_usage(
        self,
        site_id: str,
        start: datetime,
        end: datetime,
        resolution: Optional[str] = None,
    ) -> list[dict]:
        """
        Fetch usage data for a site within a date range.
        
        This is a stub implementation for future use.
        
        Args:
            site_id: The site ID to fetch usage for
            start: Start datetime
            end: End datetime
            resolution: Optional resolution parameter (e.g., "30min", "1hour")
            
        Returns:
            List of usage interval dictionaries
            
        Raises:
            AmberAPIError: If the API request fails
            NotImplementedError: Currently a stub
        """
        if not site_id:
            raise ValueError("site_id cannot be empty")
        
        logger.warning("get_usage() is currently a stub and not fully implemented")
        raise NotImplementedError(
            "get_usage() is a stub. Full implementation will be added in a future step."
        )


def main():
    """Main entry point for running the client as a script."""
    # Load token from environment
    token = os.getenv("AMBER_TOKEN")
    if not token:
        print("ERROR: AMBER_TOKEN environment variable is not set")
        print("Please set it with: export AMBER_TOKEN=your_token_here")
        return 1

    # Initialize client
    try:
        client = AmberClient(token=token)
    except Exception as e:
        print(f"ERROR: Failed to initialize AmberClient: {e}")
        return 1

    # Fetch and display sites
    try:
        sites = client.get_sites()
        print(f"\nFound {len(sites)} site(s):\n")
        
        for i, site in enumerate(sites, 1):
            site_id = site.get("id", "N/A")
            site_name = site.get("name", "N/A")
            network = site.get("network", "N/A")
            print(f"Site {i}:")
            print(f"  ID: {site_id}")
            print(f"  Name: {site_name}")
            print(f"  Network: {network}")
            print()
            
    except Exception as e:
        print(f"ERROR: Failed to fetch sites: {e}")
        return 1

    # If AMBER_SITE_ID is set, fetch current prices
    site_id = os.getenv("AMBER_SITE_ID")
    if site_id:
        print(f"AMBER_SITE_ID is set to: {site_id}")
        print("Fetching current prices...\n")
        
        try:
            prices = client.get_current_prices(site_id)
            
            if prices:
                print(f"Found {len(prices)} price interval(s). Showing first 3:\n")
                for i, price in enumerate(prices[:3], 1):
                    date = price.get("date", "N/A")
                    nem_time = price.get("nemTime", "N/A")
                    per_kwh = price.get("perKwh", "N/A")
                    renewables = price.get("renewables", "N/A")
                    
                    print(f"Interval {i}:")
                    print(f"  Date: {date}")
                    print(f"  NEM Time: {nem_time}")
                    print(f"  Price (c/kWh): {per_kwh}")
                    print(f"  Renewables (%): {renewables}")
                    print()
            else:
                print("No price data available.")
                
        except Exception as e:
            print(f"ERROR: Failed to fetch prices: {e}")
            return 1
    else:
        print("AMBER_SITE_ID not set. Skipping price fetch.")
        print("Set it with: export AMBER_SITE_ID=your_site_id_here")

    return 0


if __name__ == "__main__":
    exit(main())

