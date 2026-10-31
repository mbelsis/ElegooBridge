FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY elegoobridge ./elegoobridge
ENV PYTHONUNBUFFERED=1
# Uploaded print files; a named volume keeps them across restarts.
RUN mkdir -p /data/ftp && chown nobody:nogroup /data/ftp
USER nobody
CMD ["python", "-m", "elegoobridge"]
