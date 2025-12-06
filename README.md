Pour les singes qui font du son


docker build -t monkey-resonance .
docker run --device /dev/snd:/dev/snd monkey-resonance:latest detect-sc.py
docker run -it --device /dev/snd:/dev/snd monkey-resonance:latest

En docker compose (y'a un volume pour les enregistrements)
docker compose build
docker compose run mkr detect-sc.py
docker compose run -it mkr


#TODO : 
    - Séparer le mcp du serveru audio (Systeme de queues asynchones?)
    - Passer les conteneurs en user pas root (c'est mieux pour que les fichiers enregistrés gardent les bons droits hors conteneur + bonne pratique globale de sécu)
    - Ajouter un docker de "front" (un chat simple quoi) pour avoir plus de contrôle sur la manière dont intéragissent le llm et le MCP
    - Gérer les ressources / connaissances mises à dispo du MCP. Exposer les effets enregistrés, exposer la documentation de pyo/des effets.