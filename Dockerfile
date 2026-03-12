FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY src /app/src

RUN pip install --no-cache-dir .

COPY docs /app/docs
COPY scripts /app/scripts

EXPOSE 8080 2222

CMD ["python", "-m", "cli_device_sim", "serve", "--api-host", "0.0.0.0", "--api-port", "8080", "--ssh-host", "0.0.0.0", "--ssh-port", "2222", "--db-path", "/app/data/sim.db", "--ssh-host-key-path", "/app/data/host_key.pem"]

