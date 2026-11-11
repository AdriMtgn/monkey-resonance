# AGENTS.md — instructions projet pour les agents

Réponds en français, sauf demande contraire.

## Contexte

Monkey Resonance : application audio Python (**Pedalboard** / JUCE) avec un
serveur MCP et une API FastAPI pour piloter les pistes et les effets à
distance. pyo a été retiré : l'état précis du projet est décrit dans
`ETAT_ACTUEL.md`.

## Environnement de travail (container dev)

- Le repo est monté dans le container : **`/base_app` = racine du repo** (hôte).
- Python 3.12 dans `/opt/venv` (pedalboard, fastapi, mcp, pytest, ruff).
- Données : `/monkey-resonance` (`records/`, `saved_effects/`,
  `saved_midi_maps/`) — montage hôte.
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

- **Un seul thread de contrôle audio** : la capture, le traitement des pistes,
  le mix des bus et le mix de la boucle se font dans `_audio_loop`
  (`app/libs/mixer.py`, classe `MixerEngine`). `AudioStream` n'est plus qu'un
  processeur de piste (ou un moteur autonome pour les tests). Les mutations
  (effets, mute, volume, balance, routage, looper) passent par les locks du
  moteur et des pistes. Ne jamais appeler `read()`/`write()` d'un stream
  Pedalboard depuis un thread FastAPI ou MCP, et ne pas ouvrir une seconde
  capture (la carte est en exclusif). Voir `ETAT_ACTUEL.md`.
- **Latence first** : le mixer ne doit ajouter ni file, ni thread, ni buffer.
  Toutes les pistes sont traitées et sommées dans le même bloc que la capture.
  Une modification de routage doit rester une mise à jour d'état sous lock,
  jamais une reconfiguration de stream.
- **`app/main.py` définit `AudioStream`, `audio_devices`, `inputs` et
  `stream`** : ces noms sont lus à l'exécution via
  `sys.modules["__main__"].__dict__` par `app/monkey_api/api.py` et
  `app/server/server.py`. `stream` est un `MixerEngine`, `inputs` est
  `stream.inputs` (une piste `AudioStream` par input logique). Ne pas les
  renommer ni les supprimer, même s'ils semblent inutilisés.
- `app/monkey_api/api.py` et `app/server/server.py` sont proches mais pas
  identiques : le MCP a en plus le looper et l'analyse. La fusion en une
  Control API est prévue (`PLAN_SEPARATION_MCP.md`, encore obsolète). Ne pas
  dupliquer davantage la logique entre les deux.
- Effets : `app/libs/audio_stream.py` (chaîne d'effets par piste, looper) +
  `app/libs/effect_lib.py` (traduction des chemins pyo vers Pedalboard). Les
  chaînes sauvegardées sont dans `/monkey-resonance/saved_effects/*.json`.
  Après un redémarrage, recharger la chaîne de référence
  `bass_clear_warm_punch` (`load_input_effects(0, ...)`).
- Mixer : `app/libs/mixer.py` (parsing `AUDIO_INPUTS` / `AUDIO_OUTPUTS`,
  matrice `input × bus`, balance, gains gauche/droite, bus stéréo). Les outils
  MCP de configuration sont dans `app/server/server.py` (`get_mixer`,
  `add_input`, `set_route`, `add_output`, etc.) et ont leurs équivalents REST
  sous `/mixer/...`.
- Performance / MIDI : `app/libs/performance.py` (presets, bypass, looper,
  mappings, `saved_midi_maps/`) et `app/libs/midi_control.py` (MIDI brut
  `/dev/snd/midiC*D*`, pas de `/dev/snd/seq`). `main.py` expose aussi
  `performance` et `midi_listener` dans `__main__`. Le listener ne doit jamais
  appeler `read()`/`write()` audio : il passe par `dispatch_event()` et les
  méthodes publiques des pistes. `MKR_MIDI=0` désactive le listener.

## Lancer l'application

```bash
make run        # python main.py (MCP activé par défaut)
make run-mcp    # MCP en arrière-plan (port 8005, /mcp)
make run-api    # API FastAPI à la place du MCP (port 8005, /docs)
```

`--with_mcp` et `--with_api` sont exclusifs (même port).

## Agent OpenCode (serveur dans le container)

- Démarrer le serveur : `make agent-serve` (démarre aussi le container dev).
  Le mot de passe est écrit dans `.devcontainer/tmp/opencode-password`.
- Se connecter depuis l'hôte : `make agent-host`.
- TUI dans le container : `make agent`.

## Engagement

Termine chaque tâche par un résumé : ce qui a été fait, ce qui a été vérifié
(commandes + résultats), et ce qui reste si quelque chose n'a pas pu être
vérifié dans cet environnement.
