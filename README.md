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
