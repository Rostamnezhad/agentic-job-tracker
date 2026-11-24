FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home tracker \
    && mkdir /data && chown tracker:tracker /data
COPY job_tracker ./job_tracker
USER tracker
ENV JOB_TRACKER_WEB_DB=/data/web.sqlite3
EXPOSE 8000
VOLUME ["/data"]
CMD ["python", "-m", "job_tracker", "serve", "--host", "0.0.0.0", "--port", "8000"]
