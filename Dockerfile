ARG BEETS_VERSION=2.0.0
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    findutils \
    flac \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
ARG BEETS_VERSION
RUN pip install --no-cache-dir -r requirements.txt beets==${BEETS_VERSION}

COPY . .

EXPOSE 8337
CMD ["python", "run.py"]
