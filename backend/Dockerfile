FROM docker.1ms.run/python:3.11-slim

WORKDIR /app

RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    nodejs \
    npm \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @tencent-qqmail/agently-cli

COPY requirements.txt .
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /app/uploads/outputs

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
