# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy only necessary files
COPY . .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Set environment variables from the .env file
# NOTE: .env should be mounted during docker-compose up, not copied
ENV PYTHONUNBUFFERED=1

# Run your app
CMD ["python", "main.py"]

