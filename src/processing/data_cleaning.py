import pandas as pd

def clean_prices_data(file_path, output_path):
    """
    Cleans and validates the prices data.
    - Removes duplicates.
    - Ensures date column is in datetime format.
    - Removes rows with missing or invalid critical data.
    - Handles missing values in non-critical columns.
    """
    print(f"Processing prices data: {file_path}")
    df = pd.read_csv(file_path)

    # Remove duplicates
    df = df.drop_duplicates()

    # Convert 'date' column to datetime
    df['date'] = pd.to_datetime(df['date'], errors='coerce')

    # Drop rows with invalid dates or missing critical fields
    df = df.dropna(subset=['date', 'perKwh', 'renewables', 'spotPerKwh'])

    # Ensure numeric columns have valid values
    df = df[(df['perKwh'] >= 0) & (df['renewables'] >= 0)]

    # Fill missing 'tariffInformation' with "unknown"
    df['tariffInformation'] = df['tariffInformation'].fillna("unknown")

    # Save cleaned data
    df.to_csv(output_path, index=False)
    print(f"Cleaned prices data saved to {output_path}")


def clean_usage_data(file_path, output_path):
    """
    Cleans and validates the usage data.
    - Removes duplicates.
    - Ensures date column is in datetime format.
    - Removes rows with missing or invalid critical data.
    - Handles missing values in non-critical columns.
    """
    print(f"Processing usage data: {file_path}")
    df = pd.read_csv(file_path)

    # Remove duplicates
    df = df.drop_duplicates()

    # Convert 'date' column to datetime
    df['date'] = pd.to_datetime(df['date'], errors='coerce')

    # Drop rows with invalid dates or missing critical fields
    df = df.dropna(subset=['date', 'kwh', 'perKwh', 'cost'])

    # Ensure numeric columns have valid values
    df = df[(df['kwh'] >= 0) & (df['perKwh'] >= 0) & (df['cost'] >= 0)]

    # Fill missing 'tariffInformation' with "unknown"
    df['tariffInformation'] = df['tariffInformation'].fillna("unknown")

    # Save cleaned data
    df.to_csv(output_path, index=False)
    print(f"Cleaned usage data saved to {output_path}")


if __name__ == "__main__":
    # File paths
    prices_input = "./prices_data.csv"
    prices_output = "./prices_data_cleaned.csv"

    usage_input = "./usage_data.csv"
    usage_output = "./usage_data_cleaned.csv"

    # Clean and validate data
    clean_prices_data(prices_input, prices_output)
    clean_usage_data(usage_input, usage_output)