FROM python:3-slim

WORKDIR /app
COPY adsb_feed.py adsb_web.py ./

EXPOSE 8080
ENTRYPOINT ["python3", "adsb_web.py"]
CMD ["--host", "127.0.0.1", "--port", "30003"]
