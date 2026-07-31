# Political Alpha Tracker - Institutional Cloud Deployment
FROM python:3.11-slim

# Install system dependencies (needed for Playwright/Headless browsers if used later, and build tools)
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Set environment variables for production
ENV ENVIRONMENT=production
# In production, proxy credentials would be passed via Secrets Manager
ENV HTTP_PROXY=""
ENV HTTPS_PROXY=""

# Command to run the alpha pipeline continuously (e.g., using a scheduler or loop inside main.py)
CMD ["python", "main.py"]
