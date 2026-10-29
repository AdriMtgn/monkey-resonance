# 🚀 Guide de Développement - Monkey Resonance

Ce guide explique comment utiliser les outils et commandes créés pour développer sur Monkey Resonance.

---

## 📦 Environnement de développement

L'application s'exécute dans un **container Docker** (image `monkey-resonance-dev`) avec :
- Python 3.12 + pyo, fastapi, mcp, pytest, ruff
- OpenCode agent configuré avec LiteLLM (Qwen3.5-35B)
- Carte son `/dev/snd` montée (AudioBox USB 96)
- Répertoire `/base_app` = montage du repo hôte

---

## 🛠️ Workflow de développement simplifié

### Démarrage rapide

```bash
# 1. Démarrer le devcontainer + agent OpenCode (tout en un)
make dev

# 2. Lancer l'application avec MCP (image DEV - recommandée pour dev)
make run-mcp

# 3. Poser une question à l'agent OpenCode
make ask "Explique comment fonctionne la chaîne d'effets"
```

### Comprendre chaque commande

#### Développement (Image DEV)

| Commande | Description |
|----------|-------------|
| `make dev` | Démarrer devcontainer + OpenCode agent (recommandé) |
| `make app` | Démarrer/restart l'application MCP (auto-devcontainer si nécessaire) |
| `make ask "..."` | Interroger OpenCode dans le container |
| `make reload-mcp` | Recharger le MCP quand l'app redémarre |
| `make agent` | OpenCode TUI standalone dans le container |
| `make agent-serve` | Démarrer le serveur OpenCode pour connexion distante |
| `make agent-host` | Connecter le TUI OpenCode depuis l'hôte |
| `make run` | Lancer l'application pure (image DEV) |
| `make run-mcp` | Lancer avec MCP (image DEV) |
| `make run-api` | Lancer avec API (image DEV) |

#### Production (Image PROD)

| Commande | Description |
|----------|-------------|
| `make run-prod` | Lancer l'application (image PROD) |
| `make run-prod-mcp` | Lancer avec MCP (image PROD) |

**Note**: L'image PROD nécessite un rebuild après les changements de code (`docker build -t monkey-resonance:latest -f Dockerfile .`)

---

### Images Docker

| Image | Usage | Taille |
|-------|-------|--------|
| `monkey-resonance-dev` | Développement (OpenCode, MCP, devtools) | ~3.5GB |
| `monkey-resonance` | Production (application uniquement) | ~2.2GB |

### Rebuild l'image PROD

Après des changements dans `Dockerfile` ou `requirements.txt` :

```bash
# Rebuild complet
docker build -t monkey-resonance:latest -f Dockerfile .

# Ou via docker compose
docker compose -f docker-compose.yml build --no-cache
```

---

### Images Docker (comparaison)

| Aspect | Image DEV | Image PROD |
|--------|-----------|------------|
| Taille | ~3.5GB | ~2.2GB |
| OpenCode | ✅ Installé | ❌ Non installé |
| MCP | ✅ (1.6.0) | ✅ (1.6.0) |
| Dev tools | ✅ pytest, ruff | ❌ |
| LiteLLM | ✅ Configuré | ❌ |
| Base | monkey-resonance | ubuntu:24.04 |


---

## 🤖 Utilisation de l'agent OpenCode

### Configuration automatique

L'agent OpenCode est **automatiquement configuré** pour :
1. Détecter le MCP `monkey-resonance` via `opencode.jsonc`
2. Utiliser LiteLLM comme fournisseur de modèles (Qwen3.5-35B)
3. Autoriser les commandes de développement (`make *`, `uv pip install *`)

### Interagir avec l'agent

#### Dans le container (TUI)
```bash
make agent
```

#### Depuis l'hôte (SSH)
```bash
# Sur Mac/Linux
make agent-host

# Sur Windows (WSL)
make agent-host-ssh
```

#### Via ask (recommandé pour questions rapides)
```bash
make ask "Quelles sont les pistes audio actives ?"
make ask "Comment sauvegarder une configuration audio ?"
make ask "Vérifier la syntaxe de app/libs/audio_stream.py"
```

### Permissions agent

L'agent a les permissions suivantes dans `opencode.jsonc` :
- ✅ `make *` - Toutes les commandes Make
- ✅ `uv pip install *` - Installation de dépendances
- ✅ `git push *` - Demande confirmation avant push
- ✅ `read *` - Lecture de tous les fichiers
- ✅ `edit *` - Édition de tous les fichiers

---

## 🎵 Configuration audio

### Détection automatique (dépréciée)

Ancienne méthode : détection automatique via PortAudio (instable).

### Configuration fixe (recommandée)

Depuis les derniers changements, la configuration audio est **fixe** pour l'AudioBox USB 96 :

```python
# app/main.py
input_audio_device = 0        # AudioBox USB 96: hw:0,0
output_audio_device = 0       # AudioBox USB 96: hw:0,0
input_nbchannels = 2          # Stéréo
output_nbchannels = 2         # Stéréo
```

**Pourquoi fixe ?**
- L'AudioBox USB 96 est toujours sur `hw:0,0` dans le container
- Configuration plus rapide et prévisible
- Évite les problèmes de détection lors du boot

### Vérifier la détection audio

```bash
docker compose -f docker-compose.yml run --rm mkr python -c "
import pyo
devices = pyo.pa_list_devices()
for i, d in enumerate(devices[0]):
    print(f'Input {i}: {d[\"name\"]}')
"
```

**Output attendu** :
```
Input 0: AudioBox USB 96: Audio (hw:0,0), ...
```

---

## 🔌 MCP (Model Context Protocol)

### Architecture

```
┌─────────────────┐     ┌──────────────┐     ┌──────────────┐
│   OpenCode      │────▶│  mcp-stdio.sh│────▶│  mcp.py      │
│   (TUI/Agent)   │◀────│  (wrapper)   │◀────│  (FastMCP)   │
└─────────────────┘     └──────────────┘     └──────────────┘
                                                               │
                                                               ▼
                                                        FastAPI on port 8005
```

### Dépannage MCP

Si le MCP ne démarre pas :

```bash
# Recharger le MCP
make reload-mcp

# Vérifier que mcp<2 est installé
docker compose -f docker-compose.dev.yml run --rm mkr pip list | grep mcp

# Tester le démarrage manuel
timeout 5 docker compose -f docker-compose.yml run --rm --service-ports mkr \
  python app/monkey_mcp/mcp.py
```

### Outils MCP disponibles

Les outils MCP sont définis dans `app/monkey_mcp/mcp.py`. Exemples :
- `global_status()` - Status global de l'application
- `get_audio_devices()` - Liste des devices audio
- `start_input_recording(index)` - Démarrer l'enregistrement
- `stop_input_recording(index)` - Arrêter l'enregistrement

---

## 🧪 Tests et validation

### Linting
```bash
make lint   # ruff check app/
```

### Tests unitaires
```bash
make test   # pytest tests/ app/
```

### Validation manuelle

```bash
# Valider les cibles Make
make -n dev app ask reload-mcp

# Valider docker-compose
docker compose config
docker compose -f docker-compose.dev.yml config

# Valider syntaxe Python
python3 -m py_compile app/monkey_mcp/mcp.py
python3 -m py_compile app/main.py
```

---

## 📁 Structure des scripts

```
.devcontainer/scripts/
├── dev-start.sh        # Démarrer devcontainer + agent OpenCode
├── app-start.sh        # Démarrer l'application MCP
├── ask-opencode.sh     # Poser une question à l'agent
├── mcp-stdio.sh        # Script stdio pour MCP
├── setup-mcp-for-opencode.sh  # Configurer MCP pour OpenCode
├── start-mcp.sh        # Démarrage MCP
└── agent-server.sh     # Serveur OpenCode (variables LiteLLM)
```

### Scripts wrapper - Comment ils fonctionnent

#### `dev-start.sh`
```bash
# 1. Check si devcontainer tourne
# 2. Sinon, docker compose up dev
# 3. Start OpenCode agent server si nécessaire
# 4. Lancer TUI OpenCode
```

#### `app-start.sh`
```bash
# 1. Check si devcontainer tourne
# 2. Sinon, start devcontainer (via make dev)
# 3. docker compose up app
```

#### `ask-opencode.sh`
```bash
# 1. Check credentials OpenCode
# 2. Lancer `opencode` avec credentials
# 3. Passer la question en argument
```

---

## 🔑 Variables d'environnement

### LiteLLM (pour OpenCode)
```bash
export LITELLM_BASE_URL="http://litellm.montalab/v1/"
export LITELLM_API_KEY="sk-..."
```

Ces variables sont **automatiquement exportées** dans :
- `~/.bashrc` (dans l'image dev)
- `agent-server.sh` (pour le serveur OpenCode)

### MCP
```bash
export MCP_PORT=8005
export MCP_MOUNT_PATH=/
```

### OpenCode
```bash
export OPENCODE_AGENT_PORT=4096
export OPENCODE_AGENT_HOST=0.0.0.0
```

---

## 🐛 Dépannage

### "No audio shared with docker"
```bash
# Vérifier que /dev/snd est monté
docker compose -f docker-compose.yml config | grep devices

# Monter manuellement si nécessaire
docker compose -f docker-compose.yml up --build --device /dev/snd:/dev/snd
```

### "MCP server not running"
```bash
# Vérifier le port
netstat -tlnp | grep 8005

# Redémarrer MCP
make reload-mcp

# Rebuild l'image si nécessaire
make dev-clean
make dev
```

### OpenCode credentials manquants
```bash
# Vérifier le fichier de password
cat .devcontainer/tmp/opencode-password

# Si manquant, relancer agent-serve
make agent-serve
```

### Container ne démarre pas
```bash
# Nettoyer les containers
make clean

# Reconstruire
make dev
```

---

## 🚢 Workflow de commit

### Avant de commit

1. **Valider les tests** :
   ```bash
   make lint
   make test
   ```

2. **Vérifier les changements** :
   ```bash
   git status
   git diff
   ```

3. **Tester le build Docker** (optionnel mais recommandé) :
   ```bash
   docker build -f Dockerfile.dev -t test-dev:latest .
   ```

### Commits recommandés

```bash
# Ajouter tous les changements
git add -A

# Commit avec message conventionnel
git commit -m "feat: Add simplified dev workflow

- Add make dev/app/ask/reload-mcp shortcuts
- Configure LiteLLM for Qwen3.5-35B
- Fix audio device detection for AudioBox USB 96

Tests validated:
✅ Make targets exist
✅ Docker compose validates
✅ AudioBox detected (device 0)
"
```

### Push (avec confirmation)

```bash
# Git push demande confirmation (configuré dans opencode.jsonc)
git push
```

---

## 📚 Ressources supplémentaires

- [`PLAN_SEPARATION_MCP.md`](PLAN_SEPARATION_MCP.md) - Architecture MCP
- [`MCP_WITH_OPENCODE.md`](MCP_WITH_OPENCODE.md) - Intégration MCP + OpenCode
- [`AGENTS.md`](AGENTS.md) - Instructions pour les agents

---

## 💡 Bonnes pratiques

1. **Toujours utiliser `make dev`** pour le développement
2. **Utiliser `make ask`** plutôt que de lancer l'agent manuellement
3. **Recharger le MCP** après redémarrage de l'application
4. **Ne pas modifier la config audio** - utiliser la config fixe pour AudioBox
5. **Tester avec `make lint` et `make test`** avant commit

---

**Dernière mise à jour**: 28 octobre 2026  
**Version**: v2.0 (dev workflow simplifié)
