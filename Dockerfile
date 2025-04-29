# Użyj lekkiego obrazu Alpine z Pythonem
FROM python:3.12-alpine

# Ustaw katalog roboczy
WORKDIR /app

# Skopiuj plik requirements.txt i zainstaluj zależności
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Skopiuj całą aplikację
COPY . .

# Otwórz port 80 (tak jak masz w app.run)
EXPOSE 5000

# Uruchom aplikację
CMD ["python", "app.py"]
