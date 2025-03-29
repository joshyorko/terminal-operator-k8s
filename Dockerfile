# USE LIGHTWEIGHT PYTHON BASE IMAGE
FROM python:3.10-slim

# CREATE WORKSPACE
WORKDIR /app

# COPY AND INSTALL DEPENDENCIES
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# COPY OPERATOR CODE
COPY operator/ ./operator/

# EXPOSE PORT FOR HEALTH CHECKS
EXPOSE 8080

# RUN OPERATOR WITH MIGHTY ROAR
CMD ["kopf", "run", "/app/operator/main.py", "--verbose", "--standalone", "--liveness=http://0.0.0.0:8080/healthz"]