FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 VOCA_BIND=0.0.0.0
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && useradd -m -u 10001 voca
COPY backend /app/backend
COPY widget /app/widget
COPY admin /app/admin
COPY setup.py .env.example /app/
RUN mkdir /app/data && chown -R voca:voca /app
USER voca
EXPOSE 8787
CMD ["python", "backend/run.py"]
