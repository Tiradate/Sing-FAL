FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV ICON_SKIP_RUNTIME_BOOTSTRAP=1
ENV ICON_DATA_DIR=/data

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data /app/static/uploads

EXPOSE 5000

CMD ["waitress-serve", "--listen=0.0.0.0:5000", "app:app"]
