Pour les singes qui font du son


docker build -t monkey-resonance .
docker run --device /dev/snd:/dev/snd monkey-resonance:latest python detect-sc.py
docker run -it --device /dev/snd:/dev/snd monkey-resonance:latest

En docker compose (y'a un volume pour les enregistrements)
docker compose build
docker compose run mkr python detect-sc.py
docker compose up -d mkr

docker compose run  --service-ports mkr -i main.py --with_api

#TODO :
    - Séparer le mcp du serveru audio (Systeme de queues asynchones?)
    - Passer les conteneurs en user pas root (c'est mieux pour que les fichiers enregistrés gardent les bons droits hors conteneur + bonne pratique globale de sécu)
    - Ajouter un docker de "front" (un chat simple quoi) pour avoir plus de contrôle sur la manière dont intéragissent le llm et le MCP
    - Gérer les ressources / connaissances mises à dispo du MCP. Exposer les effets enregistrés, exposer la documentation de pyo/des effets.

## Working in the container (agent / dev workflow)

L'image de production reste fine (pas de pytest/ruff). Les dépendances de dev
(pytest, ruff) vivent soit dans l'image dev (`Dockerfile.dev`), soit sont
installées à la demande dans le conteneur en cours d'exécution.

### Build

```bash
make build      # image principale (production)
make build-dev  # image dev = image principale + pytest/ruff (nécessite `make build` d'abord)
```

### Shell

```bash
make shell      # bash dans l'image principale
make shell-dev  # bash dans l'image dev
```

### Tests & lint

```bash
make test       # pytest (nécessite l'image dev, ou `make dev-deps` d'abord)
make lint       # ruff check (idem)
```

### Lancer l'app

```bash
make run        # python main.py (interactif)
make run-mcp    # python main.py --with_mcp
make run-api    # python main.py --with_api
```

### Commandes arbitraires

```bash
make exec CMD="ls -la"
make exec CMD="python -c 'import pyo; print(pyo.__version__)'"
```

### Dépendances de dev à la demande

```bash
make dev-deps   # uv pip install -r requirements-dev.txt dans le conteneur en cours
```

### Cycle de vie

```bash
make up         # docker compose up -d mkr
make down       # docker compose down
make restart    # docker compose restart mkr
make logs       # docker compose logs -f mkr
make clean      # down + suppression des images locales et volumes
```