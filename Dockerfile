# Using official Python 3.11.9 slim image as base
FROM python:3.11.9-slim

# Setting working directory
WORKDIR /app

# Copying application files
COPY http_server.py .
COPY app.py .
COPY requirements.txt .

# Installing dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Command to run the application
CMD ["python", "app.py"]