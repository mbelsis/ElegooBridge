FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY elegoobridge ./elegoobridge
ENV PYTHONUNBUFFERED=1
USER nobody
CMD ["python", "-m", "elegoobridge"]
