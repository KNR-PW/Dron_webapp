# Webowka 
1. Najpierw requirements
```bash
pip install -r requirements.txt
```
2. Potem wlaczasz zioma 
3. Kamera :
na drugim urządzeniu w tej samej sieci wejdz na  http://<IP_SERWERA>:5000/

### Ewentualnie 
1. budujesz dockera 
```bash
docker build -t webapp .
```
2. potem uruchamiasz
```bash
docker run -p 5000:5000 [id]
```
3. potem localhost:5000
4. Simulator.py i photoPost.py można uruchomić w dockerze
```bash
python photoPost.py -i [image.jpg]
```

---

## Production deployment (Docker)

- Aplikacja jest gotowa do uruchomienia na produkcji przez gunicorn (serwer WSGI) w kontenerze.
- Obraz bazowy to `python:3.12-slim`, z doinstalowanymi zależnościami systemowymi dla `opencv-python-headless`.

Kroki (skrócone):
- Zbuduj obraz.
- Utwórz wolumen na dane (obrazy i logi), np. `dron_webapp_data`.
- Uruchom kontener z mapowaniem portu 5000 i wolumenu na `/var/data`.
- Ustaw zmienne środowiskowe:
  - `SECRET_KEY` (dowolny losowy sekret w produkcji)
  - `FLASK_DEBUG=false`
  - `TRUST_PROXY=1` (gdy za reverse proxy)
  - `PREFERRED_URL_SCHEME=https` (gdy masz HTTPS)
  - (opcjonalnie) `UPLOAD_FOLDER=/var/data/images`, `LOG_FILE=/var/data/mission.log` (domyślne już takie są w Dockerfile)

Health check: zapytanie do `/healthz` zwraca `{"status": "ok"}`.

### Reverse proxy (Nginx)

- Przekieruj cały ruch HTTP→HTTPS.
- Ustaw proxy na backend `http://localhost:5000`.
- Przekazuj nagłówki `X-Forwarded-Proto`, `X-Forwarded-For`, `Host`.
- Pamiętaj o odpowiednim rozmiarze body (np. `client_max_body_size 16m;`).

Uwaga: na typowym hostingu brak kamery – endpoint `/video_feed` zwróci 503 (oczekiwane).
