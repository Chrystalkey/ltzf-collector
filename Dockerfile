FROM oapi-preimage AS oapifile
FROM python:3.13-slim-bookworm AS builder

RUN pip install poetry==1.4.2

ENV POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    POETRY_VIRTUALENVS_CREATE=1 \
    POETRY_CACHE_DIR=/tmp/poetry_cache

WORKDIR /app

COPY --from=oapifile /app/oapicode-python ./oapicode

COPY pyproject.toml poetry.lock ./

RUN --mount=type=cache,target=$POETRY_CACHE_DIR poetry install --without dev --no-root

FROM python:3.13-slim-bookworm AS runtime

LABEL maintainer="Benedikt Schäfer"
LABEL description="Collector for the LTZF"
LABEL version="0.2.1"

RUN apt-get update && apt-get install --no-install-recommends -y tesseract-ocr tesseract-ocr-deu pandoc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*
    
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH"


COPY --from=builder ${VIRTUAL_ENV} ${VIRTUAL_ENV}
COPY --from=oapifile /app/oapicode-python ./oapicode

COPY collector ./collector

VOLUME /app/locallogs

ENTRYPOINT ["python", "-m", "collector.main"]
