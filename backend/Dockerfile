FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NUMBA_CACHE_DIR=/tmp/numba
WORKDIR /srv
# rasterio's wheel links libexpat, which newer python:3.12-slim images no longer ship (deploy of 17 Oct failed on it)
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
# fail the build, not the revision, if a compiled library is missing a system package
RUN python -c "import rasterio, rasterio.features, pyogrio, pyproj, shapely, geopandas, osmnx, numba, scipy, PIL, ee"
COPY app ./app
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
