# Home Energy Analysis

## Overview

The **Home Energy Analysis** project aims to collect, store, analyse, and visualise energy usage data for an apartment in Vaucluse, Sydney. By leveraging the **Amber Electric** API, we will fetch live and historical energy data, perform usage and cost analyses, and generate insights to optimise energy consumption. Future development will investigate home electrification scenarios including solar, battery storage, and EV charging.

## Key Objectives

1. **Data Ingestion**  
   Securely integrate with Amber Electric’s API to fetch energy usage in near real-time or via scheduled tasks.  
2. **Data Storage**  
   Store usage data in a time-series database or in CSV files (locally or in cloud storage) for scalability and reliability.  
3. **Analytics & Visualisation**  
   Clean and transform data to uncover trends and patterns, and present them on interactive dashboards or reports.  
4. **Alerts & Monitoring**  
   Monitor energy usage and system performance; implement alerts for anomalies or downtime.  
5. **Documentation & Best Practices**  
   Maintain comprehensive documentation and follow clean code principles, DevOps, and CI/CD best practices.

## Project Plan (Phased Approach)

### Phase 1: Requirements & Design
- Gather requirements on data granularity, retention policy, and technical constraints.  
- Validate Amber Electric API feasibility (authentication, rate limits).  
- Outline an architecture for data flow and select hosting environment (e.g. AWS, GCP, or local).

### Phase 2: Project Setup & Code Infrastructure
- Initialise a Git repository with a well-defined directory structure.  
- Set up Python or Docker environments to ensure reproducible deployments.  
- Configure Continuous Integration (CI) with GitHub Actions to lint, test, and build the project.

### Phase 3: Data Ingestion & Storage
- Implement scheduled data ingestion from Amber Electric’s API.  
- Store raw data in CSVs (initially) and consider a time-series database (InfluxDB/TimescaleDB) as the project grows.  
- Clean and validate data against a schema and maintain versioning for raw vs cleaned datasets.

### Phase 4: Analysis & Visualisation
- Develop scripts for calculating daily, weekly, and monthly usage statistics.  
- Create dashboards or reports to highlight consumption trends, costs, and possible savings.  
- Integrate external data (e.g. weather) for deeper correlations.

### Phase 5: Monitoring & Alerting
- Monitor system metrics (CPU, memory) and ingestion health checks.  
- Implement anomaly detection on usage data; send alerts via Slack or email.  
- Centralise logs and error handling for easier debugging.

### Phase 6: Documentation & Knowledge Transfer
- Maintain a clear and structured **README.md** and code-level docstrings.  
- Provide end-user documentation (dashboards, how-tos).  
- Handover session or recording for any collaborators.

## Project Structure

Below is a suggested directory layout:
home-energy-analysis/
├── 6th Jan Notes.rtf           # Project notes
├── Amber_API_Documentation.rtf # API reference material
├── Project_Plan.rtf            # Initial project planning document
├── config/                     # Placeholder for configuration files (e.g., settings, credentials)
├── historical_data.csv         # Consolidated historical energy data (if applicable)
├── prices_data.csv             # Historical electricity pricing data
├── requirements.txt            # Python dependencies
├── src/                        # Source code directory
│   ├── README.md               # Additional documentation (specific to src folder)
│   ├── analysis/               # Scripts for analysing energy data
│   ├── ingestion/              # Data ingestion and API integration scripts
│   │   ├── amber_api.py        # Main script to interact with the Amber Electric API
│   │   └── test_amber_api_data.py # Test script for validating Amber API data
│   ├── processing/             # Scripts for data cleaning and transformation
│   └── visualisation/          # Scripts for data visualisation (e.g., dashboards, plots)
├── tests/                      # Placeholder for testing modules (unit tests, etc.)
├── usage_data.csv              # Historical energy usage data
└── venv/                       # Python virtual environment
├── bin/                    # Executables and shell scripts for virtual environment activation
├── etc/                    # Configurations for virtual environment utilities
├── include/                # C headers for Python packages
├── lib/                    # Libraries installed in the virtual environment
├── pyvenv.cfg              # Virtual environment configuration file
└── share/                  # Shared resources (e.g., Jupyter notebooks)

## Current Progress

1. **API Integration**  
   - Connected to Amber Electric API using a securely stored token.  
   - Validated the site ID and tested the availability of usage and pricing data.

2. **Data Retrieval**  
   - Fetched historical pricing and usage data starting from 24 June 2024.  
   - Utilised weekly intervals to avoid hitting rate limits.

3. **Data Storage**  
   - Storing raw data in `prices_data.csv` and `usage_data.csv` within the `data/` directory.  
   - Implemented logic to append new data while preserving existing records.

4. **Testing**  
   - Implemented a testing script (`test_amber_api_data.py`) to verify API data integrity.  
   - Confirmed each endpoint (prices, usage, forecast) returns valid data.

5. **Next Steps**  
   - Automate the data ingestion with cron jobs (weekly on Mondays at 2:00 AM).  
   - Begin exploratory data analysis (EDA) to identify usage patterns and potential cost savings.  
   - Consider transitioning from CSVs to a database solution for scalability.  
   - Develop visual dashboards to report on real-time and historical energy usage.  
   - Implement robust logging and anomaly alerts.

## Usage Instructions

1. **Installation**
   - Clone the repository:  
     ```bash
     git clone https://github.com/YourUsername/home-energy-analysis.git
     cd home-energy-analysis
     ```
   - (Optional) Create and activate a Python virtual environment:  
     ```bash
     python3 -m venv venv
     source venv/bin/activate
     ```
   - Install dependencies:  
     ```bash
     pip install -r requirements.txt
     ```

2. **Configuration**
   - Copy `.env.example` to `.env` and update the environment variables with your Amber Electric API credentials.  
   - Adjust settings in `config/settings.yaml` or `config/credentials.yaml` as required.

3. **Running the Ingestion Script**
   - Ensure your `.env` file is properly configured.  
   - From the `home-energy-analysis` root directory:  
     ```bash
     python src/ingestion/amber_api.py
     ```
   - This script will fetch new data and store it in the `data/` directory.

4. **Testing**
   - Run tests to validate data ingestion and other functionalities:  
     ```bash
     pytest tests/
     ```

5. **Contributing**
   - Please open a pull request for proposed changes.  
   - Ensure your code follows best practices for style (PEP 8 for Python) and includes documentation where appropriate.  
   - Validate all changes with existing tests, and add new test coverage for any new features.

## Best Practices & Recommendations

- **Code Style**: Use PEP 8 and automated linters (e.g. `flake8`, `black`).  
- **Security**: Keep API tokens safe (e.g. `.env` or a secure Vault); do not commit secrets to version control.  
- **Documentation**: Add docstrings for functions and maintain a clean, up-to-date **PROJECT_PROGRESS.md** for daily notes.  
- **Testing**: Implement both unit and integration tests; ensure CI checks pass before merging.  
- **Performance**: Explore a time-series database if the data volume grows significantly.

## Licence

Specify the licence under which your project is distributed, e.g. [MIT](https://opensource.org/licenses/MIT).