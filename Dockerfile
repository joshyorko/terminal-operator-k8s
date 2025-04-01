# USE LIGHTWEIGHT PYTHON BASE IMAGE
FROM python:3.10-slim

# CREATE WORKSPACE
WORKDIR /app

# COPY AND INSTALL DEPENDENCIES
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# COPY terminal_operator CODE
COPY terminal_operator/ ./terminal_operator/

# EXPOSE PORT FOR HEALTH CHECKS
EXPOSE 8080

# RUN terminal_operator WITH MIGHTY ROAR
CMD ["kopf", "run", "/app/terminal_operator/main.py", "--verbose", "--standalone", "--liveness=http://0.0.0.0:8080/healthz"]