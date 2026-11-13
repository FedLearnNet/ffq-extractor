FROM ghcr.io/fedlearnnet/python-tool-api/base-python-dep:0.7.17.dev

USER 0

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN pip install --no-cache-dir -e . \
 && chown -R nonroot:nonroot /app /opt/venv \
 && chmod -R u+rwX,g+rwX /app

USER nonroot:nonroot
CMD ["python", "main.py"]
