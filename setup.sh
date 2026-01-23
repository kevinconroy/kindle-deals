#!/bin/bash
# One-line setup for Kindle Deals Monitor

set -e  # Exit on error

echo "Starting Kindle Deals Monitor setup..."
echo

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install Python dependencies
echo "Installing Python dependencies..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Install Playwright browser
echo "Installing Playwright browser..."
playwright install chromium

# Run Python setup (config + database)
echo "Running setup..."
python setup.py

echo
echo "Setup complete! Activate the virtual environment with:"
echo "  source venv/bin/activate"
