FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .
RUN adduser --disabled-password --gecos '' --uid 1000 appuser
USER appuser
EXPOSE 8000
CMD ["dibs-http"]
