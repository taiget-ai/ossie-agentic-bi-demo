FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY ossie_demo ./ossie_demo
COPY models ./models
COPY web ./web
COPY data/fixtures ./data/fixtures
RUN pip install --no-cache-dir -e .
RUN python -m ossie_demo seed
EXPOSE 8000
CMD ["uvicorn", "ossie_demo.api:app", "--host", "0.0.0.0", "--port", "8000"]
