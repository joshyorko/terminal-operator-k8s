# APE USE LIGHTWEIGHT PYTHON BASE IMAGE
FROM python:3.10-slim

# APE CREATE WORKSPACE
WORKDIR /app

# APE COPY AND INSTALL DEPENDENCIES
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# APE COPY OPERATOR CODE
COPY operator/ ./operator/

# APE EXPOSE PORT FOR HEALTH CHECKS
EXPOSE 8080

# APE RUN OPERATOR WITH MIGHTY ROAR
CMD ["kopf", "run", "/app/operator/main.py", "--verbose", "--standalone", "--liveness=http://0.0.0.0:8080/healthz"]