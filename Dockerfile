# Use the official lightweight Python image
FROM python:3.11-slim

# Prevent Python from writing pyc files to disc and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file first (this leverages Docker's layer caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code
COPY . .

# Expose the port (Render dynamically assigns $PORT, defaulting to 8000 locally)
EXPOSE 8000

# Command to run the application, using the dynamic PORT variable
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]