# Kindle Deals Monitor

A Python-based tool to monitor Kindle book samples for price changes and deals.

## Features

- Automated monitoring of Kindle book samples
- Price tracking and deal detection
- Screenshot capture for visual verification
- Configurable check intervals
- YAML-based configuration

## Setup

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Install Playwright browsers:
```bash
playwright install chromium
```

4. Create a `config.yaml` file (see Configuration section)

## Configuration

Create a `config.yaml` file with your monitoring settings:

```yaml
check_interval: 3600  # seconds
books:
  - url: "https://www.amazon.com/..."
    title: "Book Title"
```

## Usage

Run the monitor:
```bash
python -m src.main
```

## Development

Run tests:
```bash
pytest
```
