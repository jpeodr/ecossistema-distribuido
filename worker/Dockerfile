FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Consumer de longa duração: consome a fila 'sidra_tasks' do RabbitMQ.
# -u garante logs em tempo real no 'docker compose logs'.
CMD ["python", "-u", "-m", "app.main"]
