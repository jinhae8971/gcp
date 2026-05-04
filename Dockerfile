FROM python:3.11-slim

# Korean timezone
ENV TZ=Asia/Seoul
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install Python dependencies (cached layer)
COPY requirements-dashboard.txt .
RUN pip install --no-cache-dir -r requirements-dashboard.txt

# Copy data generator script
COPY generate_dashboard_data.py .

# Default: run once and exit. Compose overrides this for the loop.
CMD ["python", "generate_dashboard_data.py"]
