FROM python:3.12-slim
RUN pip install uv --upgrade
RUN apt update && apt install -y libolm-dev
WORKDIR /app
COPY pyproject.toml .

RUN uv sync
COPY main.py .

CMD ["uv", "run", "python", "main.py"]