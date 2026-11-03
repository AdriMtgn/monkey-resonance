# MCP Monkey Resonance avec opencode

## Configuration

Ce document explique comment utiliser le MCP (Model Context Protocol) Monkey Resonance avec l'agent OpenCode.

## Configuration actuelle

Le MCP est configuré pour fonctionner dans le **container dev** (`/base_app`). L'agent OpenCode dans le container a accès aux outils MCP pour contrôler l'application audio.

### Outils MCP disponibles

| Outil | Description |
|-------|-------------|
| `list_inputs()` | Liste des entrées audio disponibles avec leur état |
| `get_input_effects(index)` | Récupère la chaîne d'effets d'une entrée |
| `mute_input(index)` | Coupe le son d'une entrée |
| `unmute_input(index)` | Réactive le son d'une entrée |
| `add_effect_to_input(index, effect_path, params, position)` | Ajoute un effet à une entrée |
| `update_effect(index, effect_path, params, position)` | Met à jour un effet |
| `remove_effect_from_input(index, effect_index)` | Supprime un effet de la chaîne |
| `save_input_effects(index, name)` | Sauvegarde la chaîne dans un JSON |
| `load_input_effects(index, name)` | Recharge une chaîne sauvegardée |
| `start_input_recording(index, filename, wet)` | Enregistre l'entrée brute (défaut) ou la sortie effet (`wet=true`) |
| `stop_input_recording(index, wet)` | Arrête l'enregistrement correspondant |
| `list_inputs_outputs()` | Liste des devices audio d'entrée/sortie |
| `set_output_volume(index, volume)` | Volume de sortie (gain stéréo) |
| `get_rms_level(index, window_size, wet)` | Niveau RMS / peak / dBFS |
| `get_pitch_info(index, wet)` | Pitch, note MIDI, confiance |
| `get_frequency_analysis(index, fft_size, wet)` | Spectre FFT, dominante, bandes |
| `get_audio_profile(index)` | Profil complet RMS + pitch + spectre |
| `global_status()` | Vérifie si le système audio fonctionne |

## Utilisation

### 1. Démarrer le serveur opencode dans le container

```bash
make agent-serve
```

Cela démarre:
- Le container dev (`mkr`)
- Le serveur opencode sur le port 4096
- Le MCP Monkey Resonance sur le port 8005

### 2. Lancer l'agent OpenCode

**Option A: TUI dans le container** (recommandé, accès direct au MCP)
```bash
make agent
```

**Option B: TUI depuis l'hôte** (se connecte au serveur container)
```bash
make agent-host
```

### 3. Vérifier la configuration MCP

Depuis le container:
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T -w /base_app mkr opencode mcp list
```

Sortie attendue:
```
✓ monkey-resonance  connected
```

### 4. Utiliser les outils MCP dans les conversations

Dans la session OpenCode, vous pouvez demander à l'agent d'utiliser les outils MCP :

**Exemple : Lister les entrées audio**
```
Utilise le MCP pour lister les entrées audio disponibles
```

**Exemple : Ajouter un effet**
```
Utilise le MCP pour ajouter un délai à l'entrée 0
```

**Exemple : Démarrer l'enregistrement**
```
Utilise le MCP pour démarrer l'enregistrement sur l'entrée 1
```

## Configuration technique

### Fichiers modifiés

- `requirements-dev.txt` : `mcp>=2.0.0` (transport HTTP streamable)
- `app/server/server.py` : `MCPServer` + `run(transport="streamable-http")`
- `opencode.jsonc` : serveur MCP distant `http://localhost:8005/mcp`
- `.devcontainer/scripts/start-mcp.sh` : lance `main.py --with_mcp` (HTTP)

### Ports utilisés

- **8005** : MCP HTTP (streamable-http, endpoint `/mcp`)
- **4096** : Serveur opencode

### Variables d'environnement

| Variable | Valeur par défaut | Description |
|----------|-------------------|-------------|
| `MCP_HOST` | `0.0.0.0` | Adresse IP pour le MCP |
| `MCP_PORT` | `8005` | Port pour le MCP |
| `MCP_TRANSPORT` | `streamable-http` | `streamable-http` (HTTP `/mcp`) ou `stdio` |

## Dépannage

### MCP non connecté

```bash
# Vérifier si le MCP est en cours d'exécution
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T mkr ps aux | grep mcp

# Redémarrer le MCP
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T -w /base_app mkr bash .devcontainer/scripts/start-mcp.sh

# Vérifier les logs
docker compose -f docker-compose.yml -f docker-compose.dev.yml exec -T mkr cat /base_app/.devcontainer/tmp/mcp.log
```

### Erreurs de connexion

Si opencode dit "ECONNREFUSED" ou "Not Found":
1. Vérifier que le MCP tourne : `curl http://localhost:8005/mcp`
2. Redémarrer le MCP avec `start-mcp.sh`
3. Redémarrer opencode avec `make agent`

### Outils non disponibles

Vérifier que le MCP est connecté :
```bash
opencode mcp list
```

Sortie attendue : `✓ monkey-resonance  connected`

## Notes importantes

1. **Audio access** : `/dev/snd` doit être monté dans le container pour que l'audio fonctionne
2. **Thread-unsafe** : Pedalboard/pyo ne peuvent être appelés que depuis un seul thread de contrôle
3. **Session MCP** : Les outils MCP peuvent être utilisés directement dans les conversations opencode
4. **Permissions** : Le fichier opencode.jsonc dans le container a des permissions d'écriture pour que l'agent puisse le modifier si nécessaire

## Futur développement

- [ ] Fusionner `app/monkey_api/api.py` et `app/monkey_mcp/mcp.py` en une seule Control API (voir `PLAN_SEPARATION_MCP.md`)
- [ ] Ajouter le support MCP pour l'hôte (nécessite l'installation de pyo et mcp sur l'hôte)
- [ ] Ajouter des outils MCP pour sauvegarder/charger les configurations d'effets
- [ ] Exposer les effets personnalisés (CustomDelay) via le MCP
