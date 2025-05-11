Pour les singes qui font du son


docker build -t monkey-resonance .
docker run --device /dev/snd:/dev/snd monkey-resonance:latest detect-sc.py
docker run -it --device /dev/snd:/dev/snd monkey-resonance:latest

En docker compose (y'a un volume pour les enregistrements)
docker compose build
docker compose run mkr detect-sc.py
docker compose run -it mkr