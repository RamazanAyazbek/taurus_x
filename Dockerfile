# Use a highly optimized, small base image for low RAM environments
FROM python:3.11-slim

# Prevent Python from writing .pyc files to disk (saves minimal space/memory)
ENV PYTHONDONTWRITEBYTECODE=1

# Force stdin, stdout and stderr to be totally unbuffered (crucial for live logs)
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if required, clear apt cache immediately to save space
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy only requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install dependencies without caching the index wheels (saves precious memory)
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project code into the container
COPY . .

# Run the central monitor script from its respective subdirectory
CMD ["python", "modules/research/main.py"]