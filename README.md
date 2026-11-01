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
    - (Fait) Passer les conteneurs en user pas root → user `mkr` (uid 1000, groupes audio/video)
    - Ajouter un docker de "front" (un chat simple quoi) pour avoir plus de contrôle sur la manière dont intéragissent le llm et le MCP
    - Gérer les ressources / connaissances mises a dispo du MCP. Exposer les effets enregistrés, exposer la documentation de pyo/des effets.

## Devcontainer + agent OpenCode

Le projet se lance en devcontainer : le container fait tourner l'app audio
(Pedalboard + `/dev/snd`) **et** un serveur OpenCode dans lequel un agent exécute ses
commandes directement dans le container (agent principal et subagents).

### 1. Build des images

```bash
make build      # image principale (production, slim)
make build-dev  # image dev = image principale + pytest/ruff/opencode
```

### 2. Credentials de l'agent (une fois sur l'hôte)

```bash
opencode auth export > .devcontainer/opencode-auth.json
```

Le fichier est gitignoré (il contient des secrets). Au create du devcontainer,
`post-create.sh` l'importe dans la base du container. Sans lui, l'agent
démarrera sans modèle connecté — refaire l'export puis
`bash .devcontainer/scripts/post-create.sh` depuis un shell du container.

### 3. Lancement

```bash
# Via VS Code : "Reopen in Container" (extension Dev Containers)
#   → repo monté dans /base_app, credentials importés (post-create),
#     serveur agent démarré sur le port 4096 (post-start, auto-forwardé).

# Via make (sans VS Code) :
make agent-serve   # démarre le container dev + le serveur agent (port 4096)
```

### 4. Agent : deux façons de bosser (elles coexistent)

```bash
make agent-host    # TUI opencode SUR L'HÔTE, connectée au serveur du
                   # container (OPENCODE_PASSWORD lu automatiquement)
make agent         # TUI opencode DANS le container (standalone)
```

Dans les deux cas, tout le shell de l'agent s'exécute dans le container
(`make test`, `make lint`, `make run`, ...). La session host et la session
container partagent le même serveur : les conversations suivies d'un côté sont
visibles de l'autre.

Détail manuel (si tu veux brancher ton propre client OpenCode depuis l'hôte) :

```bash
make agent-password   # affiche le mot de passe du serveur agent
OPENCODE_PASSWORD=$(cat .devcontainer/tmp/opencode-password) \
  opencode --server http://localhost:4096
```

### 5. Workflow dev (toujours dans le container)

```bash
make lint       # ruff check app/ (config : ruff.toml, ruff épinglé)
make test       # pytest tests/ app/
make run        # python main.py (interactif)
make run-mcp    # python main.py --with_mcp
make run-api    # python main.py --with_api
make shell-dev  # bash dans l'image dev
make exec CMD="ls -la"   # commande arbitraire dans le container
make dev-deps   # uv pip install -r requirements-dev.txt (à la demande)
```

### 6. Cycle de vie

```bash
make up-dev     # docker compose up -d avec l'image dev + repo monté
make up         # up avec l'image prod
make down       # docker compose down
make restart    # docker compose restart mkr
make logs       # docker compose logs -f mkr
make clean      # down + suppression des images locales et volumes
```

Notes :
- L'image de production reste slim : pytest/ruff/opencode ne sont que dans
  `Dockerfile.dev`.
- Le repo est monté dans `/base_app` (override dev) : les éditions de l'agent
  sont directement sur les fichiers de l'hôte.
- Le serveur agent écrit son état dans `.devcontainer/tmp/` (gitignoré) :
  `opencode-password`, `opencode-server.log`, `opencode-server.pid`.