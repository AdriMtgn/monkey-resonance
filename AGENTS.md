# AGENTS.md — instructions projet pour les agents

Réponds en français, sauf demande contraire.

## Contexte

Monkey Resonance : application audio Python (pyo / PortAudio) avec un serveur
MCP et une API FastAPI pour piloter les pistes et les effets à distance.

## Environnement de travail (container dev)

- Le repo est monté dans le container : **`/base_app` = racine du repo** (hôte).
- Python 3.12 dans `/opt/venv` (pyo, fastapi, mcp, pytest, ruff).
- Données : `/monkey-resonance` (`records/`, `saved_effects/`) — montage hôte.
- Audio : `/dev/snd` partagé avec le container (AudioBox USB 96 sur le Pi).
  Sans lui, `main.py` s'arrête avec une erreur explicite.
- **Toute commande shell s'exécute dans le container** — agent principal et
  subagents. Pas besoin de `docker exec` : tu y es déjà.

## Vérifications avant de conclure une tâche

```bash
make lint   # ruff check app/ — 0 finding attendu (config : ruff.toml)
make test   # pytest tests/ app/ — collection doit réussir
```

Notes :
- ruff est épinglé dans `requirements-dev.txt` : les règles par défaut changent
  d'une version à l'autre, ne pas updater sans relancer `make lint`.
- Un test qui échoue à cause de l'absence de carte son (`/dev/snd`) est une
  contrainte d'environnement, pas une régression : le séparer dans le résumé.

## Règles de code importantes

- **pyo est thread-unsafe** : toutes les mutations audio doivent passer par un
  seul thread de contrôle. Ne jamais appeler pyo / `AudioStream` depuis un
  thread FastAPI ou MCP. Voir `PLAN_SEPARATION_MCP.md` (la séparation
  audio-engine / MCP y est détaillée, pas encore implémentée).
- **`app/main.py` définit `AudioStream`, `audio_devices` et `inputs`** : ces
  noms sont lus à l'exécution via `sys.modules["__main__"].__dict__` par
  `app/monkey_api/api.py` et `app/monkey_mcp/mcp.py`. Ne pas les renommer ni
  les supprimer, même s'ils semblent inutilisés.
- `app/monkey_api/api.py` et `app/monkey_mcp/mcp.py` sont quasi dupliqués :
  la fusion en une Control API est prévue en phase 2
  (`PLAN_SEPARATION_MCP.md`). Ne pas dupliquer davantage la logique entre les
  deux.
- Effets : `app/libs/audio_stream.py` (chaîne d'effets) +
  `app/libs/effect_lib.py` (effets custom type `CustomDelay`). Les chaînes
  sauvegardées sont dans `/monkey-resonance/saved_effects/*.json`.

## Lancer l'application

```bash
make run        # python main.py (interactif)
make run-mcp    # + serveur MCP (port 8005)
make run-api    # + API FastAPI (port 8005, /docs)
```

## Agent OpenCode (serveur dans le container)

- Démarrer le serveur : `make agent-serve` (démarre aussi le container dev).
  Le mot de passe est écrit dans `.devcontainer/tmp/opencode-password`.
- Se connecter depuis l'hôte : `make agent-host`.
- TUI dans le container : `make agent`.

## Engagement

Termine chaque tâche par un résumé : ce qui a été fait, ce qui a été vérifié
(commandes + résultats), et ce qui reste si quelque chose n'a pas pu être
vérifié dans cet environnement.
