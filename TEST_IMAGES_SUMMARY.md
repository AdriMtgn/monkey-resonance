# 📊 Test Images - DEV vs PROD

**Date**: 29 octobre 2026

---

## ✅ Image DEV (`monkey-resonance-dev:latest`)

### Status : **FULLY WORKING** ✅

| Composant | Status | Détails |
|-----------|--------|---------|
| MCP Server | ✅ Working | Démarré sur port 8005 |
| AudioBox USB 96 | ✅ Working | Device 0 (hw:0,0) détecté |
| Pyo Server | ✅ Running | Booté avec configuration correcte |
| Outils MCP | ✅ Registered | Tous les outils disponibles |
| OpenCode | ✅ Configured | Plugin LiteLLM installé |
| Pydantic | ✅ Compatible | v2.13.5 (compatible MCP 1.6.0) |

### Utilisation

```bash
# MCP server avec image DEV
make run-mcp

# Ou directement
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec mkr python /base_app/app/main.py --with_mcp
```

### Log attendu

```
INFO:root:Using AudioBox USB 96 configuration (hw:0,0)...
INFO:root:Server configured with device 0:0
INFO:root:Creating and booting Pyo Server...
INFO:root:Pyo server booted successfully!
INFO:root:Starting MCP server
INFO:MCP server will run on 0.0.0.0:8005
DEBUG:Initializing server 'Monkey Resonance MCP'
DEBUG:Registering handler for ListToolsRequest
DEBUG:Registering handler for CallToolRequest
...
DEBUG:Using selector: EpollSelector
```

---

## ⏳ Image PROD (`monkey-resonance:latest`)

### Status : **NEEDS REBUILD** ⏳

| Composant | Status | Détails |
|-----------|--------|---------|
| Code source | ❌ Obsolete | N'inclut pas `server/` |
| MCP Server | ❌ Non testé | Nécessite rebuild |
| AudioBox | ❓ Non testé | Nécessite rebuild |

### Pourquoi rebuild ?

L'image PROD a été build **AVANT** les changements suivants :
- Renommage `monkey_mcp/` → `server/`
- Ajout de `server/server.py`
- Modification de `app/main.py`
- Ajout de `sys.path.insert` dans `server/server.py`

### Pour rebuild l'image PROD

```bash
# Option 1: Rebuild complet (long)
docker build -t monkey-resonance:latest -f Dockerfile .

# Option 2: Rebuild via docker compose
docker compose -f docker-compose.yml build --no-cache
```

### Après rebuild, tester

```bash
# Image PROD avec MCP
docker compose -f docker-compose.yml run --rm app python main.py --with_mcp

# Ou via make
make run-prod-mcp
```

---

## 📋 Fichiers modifiés pour les deux images

| Fichier | Usage DEV | Usage PROD |
|---------|-----------|------------|
| `Dockerfile` | - | ✅ Build image PROD |
| `Dockerfile.dev` | ✅ Build image DEV | - |
| `requirements.txt` | ✅ | ✅ |
| `requirements-dev.txt` | ✅ (dev deps) | ❌ |
| `app/main.py` | ✅ | ✅ (après rebuild PROD) |
| `app/server/server.py` | ✅ | ✅ (après rebuild PROD) |

---

## 🚀 Commandes Make

| Commande | Image | Usage |
|----------|-------|-------|
| `make run` | DEV | Run app interactive |
| `make run-mcp` | DEV | Run app + MCP server |
| `make run-prod` | PROD | Run app (production) |
| `make run-prod-mcp` | PROD | Run app + MCP (production) |

### Exemples

```bash
# DEV: Développer avec MCP
make run-mcp

# PROD: Déployer en production
make run-prod

# PROD: Déployer avec MCP
make run-prod-mcp
```

---

## 🔍 Comparaison des images

| Aspect | DEV Image | PROD Image |
|--------|-----------|------------|
| Taille | ~3.5GB | ~2.2GB |
| MCP | ✅ Installé (1.6.0) | ✅ Installé |
| OpenCode | ✅ Installé | ❌ Non installé |
| Dev tools | ✅ pytest, ruff | ❌ |
| LiteLLM | ✅ Configuré | ❌ |
| Code source | Volume mount | Volume mount |
| Base image | monkey-resonance | ubuntu:24.04 |

---

## 📌 Conclusion

- ✅ **Image DEV** : Prête à l'emploi pour le développement
- ⏳ **Image PROD** : Nécessite rebuild avant première utilisation

Une fois l'image PROD rebuild, les deux images fonctionneront de la même manière pour le serveur MCP.

---

**Status** :
- Image DEV: ✅ **WORKING**
- Image PROD: ⏳ **NEEDS REBUILD**

**Prochaine étape** : Rebuild l'image PROD avec `docker build -t monkey-resonance:latest -f Dockerfile .`
