# État actuel du projet — Monkey Resonance

> Document de reprise, rédigé le **2026-11-07**, mis à jour le **2026-11-09**
> (contrôle de performance et MIDI).
> Il décrit ce qui est réellement implémenté et vérifié, pas les intentions.
> Les documents plus anciens (`PLAN_SEPARATION_MCP.md`, `EXPERIMENT.md`) sont
> partiellement obsolètes : voir la section « Dettes et documents à mettre à jour ».

---

## 1. Résumé

Le moteur audio **pyo a été remplacé par Pedalboard** (`pedalboard.io.AudioStream`).
Le projet tourne donc aujourd'hui sur :

- un **moteur audio temps réel multi-pistes** dans `app/libs/mixer.py`
  (`MixerEngine`) : une capture unique, une piste indépendante par input
  logique, un mixeur de bus stéréo ;
- `app/libs/audio_stream.py` : processeur d'une piste (chaîne d'effets, mute,
  volume, looper, enregistrement) et moteur autonome pour les tests ;
- une **chaîne d'effets Pedalboard par piste** (avec compatibilité des chemins
  pyo) ;
- un **looper par piste** intégré au moteur (lecture des WAV de `records/`) ;
- l'**enregistrement et l'analyse alimentés par le moteur** (plus de capture
  secondaire, la carte son est ouverte en exclusif) ;
- un **contrôleur de performance** (`app/libs/performance.py`) : presets
  d'effets, bypass par effet, looper « un seul pad », mappings MIDI
  sauvegardables et simulables sans matériel ;
- un **listener MIDI brut ALSA** (`app/libs/midi_control.py`), qui lit
  `/dev/snd/midiC*D*` (le container n'expose pas `/dev/snd/seq`) ;
- un **serveur MCP** (activé par défaut) et une **API REST FastAPI**
  (alternative, même port) ;
- une **image Docker** dédiée `monkey-resonance-pedalboard:latest`.

Instrument de référence : **entrée 0 de l'AudioBox USB 96**, utilisée pour une
basse claire, chaleureuse et punchy. Chaîne de référence :
`/monkey-resonance/saved_effects/bass_clear_warm_punch.json` (8 effets).

---

## 2. État Git

| Élément | Valeur |
| --- | --- |
| Branche courante | `main` |
| Commit courant | `dd64bef` — merge de `exp/spotify-pedalboard` |
| Branche expérimentale | `exp/spotify-pedalboard` @ `b53ef6a` (worktree séparé) |
| Sauvegarde ancien `main` | `backup/main-local-20261107` @ `cab30cd` |
| Avance sur `origin/main` | **17 commits**, aucun push effectué |

Le merge a conservé le moteur Pedalboard, activé le MCP par défaut, conservé
`--with_api` en mode exclusif, supprimé les scripts standalone pyo et
`app/test_pyo.py`, et remplacé pyo/sounddevice/soundcard par `pedalboard` dans
les requirements.

**Travail en cours (non commité)** : moteur multi-pistes `app/libs/mixer.py`,
pistes indépendantes dans `audio_stream.py`, config `AUDIO_INPUTS` /
`AUDIO_OUTPUTS`, outils MCP et routes REST de mixer, tests `tests/test_mixer.py`,
contrôle de performance et MIDI (`app/libs/performance.py`,
`app/libs/midi_control.py`, `saved_midi_maps/`), et mise à jour de cette
documentation. Les fichiers moteur
(`audio_stream.py`, `music_analysis.py`, `audio_devices.py`, `effect_lib.py`)
ne sont plus identiques à `exp/spotify-pedalboard`.

---

## 3. Architecture

```text
AudioBox USB 96
  ├─ capture 2 canaux ──► MixerEngine (device matériel direct, 128 frames)
  │                          │
  │                          ▼
  │                    thread audio Python (MixerEngine._audio_loop)
  │                          │
  │                          ├─ input_0 (canal 0) ──► AudioStream piste 0
  │                          │      effets + fader + balance + gains L/R
  │                          ├─ input_1 (canal 1) ──► AudioStream piste 1
  │                          │      effets + fader + balance + gains L/R
  │                          │
  │                          ├─ matrice input × bus (volume par route)
  │                          │      bus main (0,1)   bus cue (2,3) …
  │                          │
  │                          ├─ file bornée par piste ──► écriture WAV dry
  │                          ├─ listeners(segment, mix) ──► analyse dry/wet
  │                          │
  │                          └─ somme des bus ──► AudioStream playback
  │                                                      │
  └─ sortie ◄────────────────────────────────────────────┘
```

Points importants :

- **Deux streams Pedalboard séparés** : un pour la capture, un pour la lecture.
  Un stream duplex ne permet pas d'écrire dans le callback (`playBuffer`
  ignoré), d'où cette séparation.
- **Un seul thread de contrôle audio** (`MixerEngine._audio_loop`). Toutes les
  mutations (ajout/suppression d'effet, mute, volume, balance, routage,
  looper) passent par les locks du moteur et des pistes.
- **Latence first** : le découpage en pistes, le traitement des effets, le
  routage et la somme des bus se font dans le même bloc que la capture.
  Aucune file, aucun thread et aucun buffer supplémentaire ne sont ajoutés.
- **Un input logique = 1 ou 2 canaux de capture**. Par défaut, un input mono
  par canal (`input_0` sur le canal 0, `input_1` sur le canal 1). La
  configuration explicite se fait par `AUDIO_INPUTS`.
- **Un output logique = un bus stéréo** mappé sur une paire de canaux
  physiques. Par défaut, un bus `main` sur les canaux 0/1. La configuration se
  fait par `AUDIO_OUTPUTS`.
- **Matrice de routage** : chaque input a un volume d'envoi vers chaque bus
  (`set_route`), plus un fader, une balance et des gains gauche/droite
  (`set_input_mix`).
- Le traitement se fait avec **`reset=False`** pour conserver l'état des
  filtres/compresseurs entre blocs (sinon clic à chaque bloc).
- La carte est ouverte sur le **device matériel direct**
  (« Direct hardware device without any conversions »), pas sur `dsnoop` :
  à 128 frames, la capture délivre le débit réel (48 000 frames/s) avec une
  latence minimale. Conséquence : la carte est exclusive, donc pas de capture
  secondaire. L'enregistrement et l'analyse sont **alimentés par le moteur**.
- Le looper **mixe dans le même bloc de sortie** que le live : il n'ajoute
  aucune latence pendant le jeu.

### Latence

| Buffer | Latence logicielle A/R |
| --- | --- |
| **128 frames (défaut)** | **≈ 5,33 ms** (capture 2,67 + sortie 2,67) |
| 64 frames | ≈ 2,67 ms |

La latence **analogique** (ADC + USB + DAC) n'est pas mesurée : Pedalboard
n'expose pas la latence matérielle de JUCE. La latence de la boucle n'ajoute
rien : le mix se fait dans le même bloc.

---

## 4. Fichiers clés

| Fichier | Rôle |
| --- | --- |
| `app/main.py` | point d'entrée : config, `MixerEngine`, MCP par défaut, `--with_api`, `--list-devices` |
| `app/libs/mixer.py` | moteur multi-pistes : capture/lecture uniques, parsing `AUDIO_INPUTS`/`AUDIO_OUTPUTS`, matrice input × bus, balance, gains L/R, master |
| `app/libs/audio_stream.py` | processeur de piste Pedalboard : chaîne d'effets, mute/volume, looper, listeners, enregistrement dry ; moteur autonome pour les tests |
| `app/libs/effect_lib.py` | résolution des effets pyo → plugins Pedalboard, `EffectSlot`, chargement des chaînes |
| `app/libs/audio_devices.py` | découverte/résolution des devices, `AudioConfig`, variables d'environnement |
| `app/libs/music_analysis.py` | analyseur alimenté par le moteur (`WetPath`, RMS, pitch/MIDI, FFT), enregistrement wet |
| `app/libs/performance.py` | contrôleur presets / bypass / looper / mappings MIDI, persistance `saved_midi_maps/`, mode apprendre, simulation d'événements |
| `app/libs/midi_control.py` | parseur MIDI brut (Program Change, CC, Note On/Off, running status), découverte des devices ALSA et listener avec reconnexion |
| `app/libs/utils.py` | chemins `/monkey-resonance/{records,saved_effects,saved_midi_maps}` et création des dossiers |
| `app/server/server.py` | serveur MCP (outils effets, mute, enregistrement, looper, analyse) |
| `app/monkey_api/api.py` | API REST historique (FastAPI), même port que le MCP |
| `docker-compose.yml` | service `mkr`, image Pedalboard, `/dev/snd`, volume de données, port 8005 |
| `docker-compose.dev.yml` | override dev : image dev, repo monté sur `/base_app`, agent OpenCode |
| `Makefile` | build, run, tests, lint, agent, `analysis-deps` |
| `scripts/` | outils hors-ligne : `analyze_loops.py`, `cut_loop.py`, `remove_silence.py` (voir § 7 bis) |
| `requirements-analysis.txt` | dépendances d'analyse épinglées de l'image de base (librosa/scipy/soundfile) |
| `tests/` | tests hors-ligne (moteur, effets, looper, analyse, devices) |

Le contrat historique est conservé : `AudioStream`, `audio_devices`,
`inputs` et `stream` sont définis dans `app/main.py` et lus à l'exécution par
l'API et le MCP via `sys.modules["__main__"].__dict__`. **Ne pas les
renommer.** `stream` est un `MixerEngine` ; `inputs` est `stream.inputs`,
c'est-à-dire la liste des pistes `AudioStream`. Deux globals supplémentaires
sont exposés de la même façon : `performance` (`PerformanceController`) et
`midi_listener` (`MidiListener`).

---

## 5. Configuration

Variables d'environnement lues par `load_config()` — toutes optionnelles.

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `AUDIO_INPUT_DEVICE` | auto (AudioBox direct) | nom exact, sous-chaîne ou index |
| `AUDIO_OUTPUT_DEVICE` | auto (AudioBox direct) | idem |
| `AUDIO_RECORD_DEVICE` | = entrée | conservé pour compatibilité (l'enregistrement vient du moteur) |
| `AUDIO_SAMPLE_RATE` | `48000` | taux d'échantillonnage |
| `AUDIO_BUFFER_SIZE` | `128` | frames par bloc ; `64` validé |
| `AUDIO_INPUT_CHANNELS` | `2` | canaux d'entrée |
| `AUDIO_OUTPUT_CHANNELS` | `2` | canaux de sortie |
| `AUDIO_START_MUTED` | `0` | démarre chaque piste muette (sécurité larsen) |
| `AUDIO_GLOBAL_VOLUME` | `1.0` | alias historique du master (voir `AUDIO_MASTER_VOLUME`) |
| `AUDIO_MASTER_VOLUME` | = `AUDIO_GLOBAL_VOLUME` | gain master après le mix des bus |
| `AUDIO_INPUTS` | une piste mono par canal | layout des inputs, ex. `bass:0;keys:0,1` |
| `AUDIO_OUTPUTS` | `main:0,1` | layout des bus, ex. `main:0,1;cue:2,3` |
| `AUDIO_ALLOW_FEEDBACK` | `0` | autorise le feedback JUCE |
| `MCP_HOST` | `0.0.0.0` | bind du MCP / de l'API |
| `MCP_PORT` | `8005` | port du MCP / de l'API |
| `MCP_TRANSPORT` | `streamable-http` | `stdio` pour un client qui lance le process |
| `MKR_MIDI` | `1` | `0`/`false`/`off` désactive le listener MIDI (utile pour les tests ou si le device est occupé) |
| `MKR_MIDI_CONFIG` | — | chemin absolu d'un fichier de mapping JSON (prioritaire sur `MKR_MIDI_MAP`) |
| `MKR_MIDI_MAP` | — | nom d'un profil de `saved_midi_maps/<nom>.json` à charger au démarrage |
| `MKR_START_PRESET` | — | preset d'effets à charger au démarrage (sinon `startup_preset` du mapping) |
| `MKR_PORT` | `8005` | port publié par Docker (peut différer de `MCP_PORT` en dev, réseau hôte) |
| `MKR_DATA` | `/home/ubuntu/monkey-resonance` | dossier hôte monté sur `/monkey-resonance` |

Résolution des devices : un index explicite ou un nom exact gagne toujours ;
sinon une sous-chaîne est cherchée (les correspondances multiples préfèrent le
device direct) ; sinon l'AudioBox direct est choisie, puis le device par défaut.
`--list-devices` affiche la liste réelle.

Les variables `MKR_MIDI*` et `MKR_START_PRESET` ne passent pas par
`load_config()` : elles sont lues directement par `main.py` et
`PerformanceController` au démarrage. `docker-compose.yml` les transmet au
container depuis l'environnement hôte ou un fichier `.env`
(`MKR_MIDI_MAP=bass_board make run-mcp` fonctionne donc directement).

---

## 6. Effets

- Chaque input logique est une piste `AudioStream` avec sa propre chaîne en
  mémoire (`effects_chain`), protégée par son lock. `load_input_effects(0, …)`
  ne charge donc que la piste 0.
- Les effets sont des plugins Pedalboard (`HighpassFilter`, `LowShelfFilter`,
  `PeakFilter`, `Compressor`, `Gain`, `Limiter`, `Chorus`, `Delay`, `Reverb`, …).
- Compatibilité pyo conservée dans `effect_lib.py` : les chemins
  `pyo.lib.filters.ButHP`, `pyo.lib.effects.Chorus`, etc. sont traduits vers
  des plugins Pedalboard. Les noms `pedalboard.*` sont aussi acceptés.
- Sauvegarde/chargement : `/monkey-resonance/saved_effects/<nom>.json`, format
  `{"engine": "pedalboard", "effect_chain": [{"effect": ..., "params": {...},
  "enabled": true}]}`. `enabled` est optionnel (défaut `true`) et relu au
  chargement.
- **Bypass** : chaque effet porte un booléen `enabled`. Un effet bypassé garde
  ses plugins construits (réactivation immédiate) mais n'est pas inclus dans
  le `Pedalboard` traité. On peut le cibler par position ou par chemin
  (`pedalboard.Delay`, `pyo.lib.effects.Delay`, …) ; si le chemin apparaît
  plusieurs fois, c'est la première occurrence qui est utilisée.
- L'état des effets (délais, réverbes) est conservé d'un bloc à l'autre.
- **Au redémarrage, la chaîne est perdue** : il faut recharger
  `bass_clear_warm_punch` via `load_input_effects(0, "bass_clear_warm_punch")`.

Chaîne de référence `bass_clear_warm_punch` (8 effets) :

1. Highpass 30 Hz
2. LowShelf 180 Hz, +3 dB
3. Peak 350 Hz, −2,5 dB (retire le « boueux »)
4. Peak 1500 Hz, +1,5 dB (clarté)
5. HighShelf 4000 Hz, −2 dB (douceur)
6. Compressor −18 dB, ratio 3, attaque 20 ms, release 150 ms
7. Gain +3 dB (punch)
8. Limiter −1 dB

---

## 6 bis. Mixer global

- **Inputs** : `MixerEngine.inputs`, une piste par input logique. Chaque piste
  traite 1 ou 2 canaux de la capture, possède sa chaîne d'effets, son fader
  (`global_volume`), son mute et son looper.
- **Outputs** : bus stéréo logiques (`OutputBus`), mappés sur une paire de
  canaux physiques. Un bus mono est possible en donnant le même canal à
  gauche et à droite.
- **Routes** : matrice `input × output`. `set_route(input, output, volume)`
  règle le volume d'envoi d'une piste vers un bus.
- **Balance / gauche-droite** : `set_input_mix(index, balance=…,
  left_gain=…, right_gain=…)`.
  - `balance` : −1 = gauche, 0 = centre, +1 = droite (loi linéaire, centre =
    unité).
  - `left_gain` / `right_gain` : gains linéaires appliqués aux côtés gauche et
    droit avant le routage.
- **Volumes** : fader de piste (`set_input_mix(volume=…)` ou
  `set_input_volume`), volume de bus (`set_output_volume`), master
  (`set_master_volume`), mute de bus (`mute_output`), mute master
  (`mute_master`).
- **Latence** : le mix est calculé dans le bloc courant, sans file ni buffer.
  La latence logicielle reste `(capture_block + buffer_size) / sample_rate`.
- **Défauts** : un nouvel input est routé à 1.0 vers le bus 0 et à 0.0 vers
  les autres bus. Un nouveau bus ne reçoit rien tant qu'une route n'est pas
  réglée.

---

## 6 ter. Performance et MIDI

Le contrôleur `PerformanceController` (`app/libs/performance.py`) centralise
tout ce qui sert à jouer sans passer par un écran : presets, bypass, looper et
mappings MIDI. Il est créé par `main.py`, expose `performance` dans `__main__`
et sert aussi bien au MCP, à l'API REST qu'au listener MIDI ou à la simulation.
Il **ne fait aucun `read()`/`write()` audio** : il n'appelle que les méthodes
publiques des pistes `AudioStream`, qui prennent leurs locks.

### Presets d'effets

- Les presets sont les JSON valides de `saved_effects/` contenant une liste
  `effect_chain` (ou une liste à l'ancienne). Les fichiers invalides et les WAV
  sont ignorés.
- L'ordre de performance vient du champ `order` (ou `preset_order`) du mapping
  actif ; les presets absents sont filtrés. Sans ordre configuré, l'ordre
  alphabétique des fichiers est utilisé.
- `next_preset` / `previous_preset` bouclent en fin de liste. Si aucun preset
  n'est courant, `next` prend le premier, `previous` le dernier.
- `apply_preset` **conserve le fader de la piste par défaut**
  (`keep_volume=True`) ; `keep_volume=False` restaure le `global_volume`
  enregistré dans le JSON du preset.
- Un changement de preset ne touche ni le mute, ni la balance, ni le routage.

### Bypass

- `toggle_effect(target)` inverse l'état ; `set_effect_enabled(target, enabled)`
  le force. `target` est une position (`0`, `1`, …) ou un chemin d'effet
  (`pedalboard.Delay`, `pyo.lib.effects.Delay`, …).
- Le premier effet correspondant au chemin est utilisé s'il y a des doublons.

### Looper « un seul pad »

`loop_toggle` enchaîne les trois états avec un seul bouton :

1. aucun enregistrement ni lecture → démarre l'enregistrement ;
2. enregistrement en cours → l'arrête, sauvegarde le WAV dans `records/` et
   lance sa lecture en boucle ;
3. lecture en cours → l'arrête.

Les actions séparées `loop_record`, `loop_play`, `loop_stop` restent
disponibles. `loop_play` utilise le dernier enregistrement connu de la piste,
sinon le WAV le plus récent de `records/`.

### Device MIDI

- Le container n'a pas `/dev/snd/seq` : `mido`/`python-rtmidi` (ALSA sequencer)
  ne sont pas utilisables. `app/libs/midi_control.py` lit donc directement les
  devices **raw MIDI** `/dev/snd/midiC*D*` (sur le Pi :
  `/dev/snd/midiC0D0`, le port DIN de l'AudioBox USB 96).
- Le listener ouvre le device en non bloquant (`select`), se reconnecte toutes
  les 2 s si la pédale est débranchée, et republie son état dans
  `midi_status()` (`connected`, `device`, `error`, `messages`).
- Le container partage `/dev/snd` mais pas toujours `/proc/asound` : si le nom
  de carte (`AudioBox`) ne peut pas être résolu, le listener retombe sur le
  premier device raw MIDI disponible (avec un log). Un chemin `/dev/...`
  explicite reste strict.
- Le device raw est **exclusif** : `amidi -d` ne peut pas lire en même temps
  que l'application. Couper le listener avec `MKR_MIDI=0` avant un diagnostic.
- Le parseur gère Program Change, Control Change, Note On/Off, le *running
  status*, et ignore SysEx, l'horloge et l'active sensing. Un Note On de
  vélocité 0 est normalisé en Note Off.

### Format d'un mapping

Deux formats sont acceptés : plat, ou avec une section `midi` imbriquée (pour
rester proche de l'ancien exemple `triggers.json`).

```json
{
  "name": "bass_board",
  "device": "AudioBox",
  "channel": 0,
  "debounce_ms": 150,
  "input_index": 0,
  "startup_preset": "bass_clear_warm_punch",
  "order": ["bass_clear_warm_punch", "bass_mid_growl"],
  "bindings": [
    {
      "id": "pc0",
      "source": {"type": "program_change", "number": 0},
      "action": {"type": "preset", "target": "bass_clear_warm_punch"}
    },
    {
      "id": "cc21",
      "source": {"type": "control_change", "controller": 21, "mode": "press"},
      "action": {"type": "next_preset"}
    },
    {
      "id": "pad36",
      "source": {"type": "note_on", "number": 36},
      "action": {"type": "loop_toggle"}
    }
  ]
}
```

Sources (`source`) :

| Champ | Valeurs | Remarque |
| --- | --- | --- |
| `type` | `program_change`, `control_change`, `note_on`, `note_off` | un `note_on` accepte aussi le Note Off correspondant pour les modes `release`/`toggle` |
| `number` | 0–127 | note ou numéro de program |
| `controller` | 0–127 | obligatoire pour `control_change` |
| `channel` | 0–15 | absent = canal du mapping (`channel`) ; **canal 0 = canal MIDI 1** |
| `mode` | `press`, `release`, `toggle`, `value` | `value` réservé aux actions de volume |
| `threshold` | 0–127, défaut 64 | seuil « pressé » d'un CC |

Actions (`action`) :

| Type | Champs | Effet |
| --- | --- | --- |
| `preset` | `target` | charge un preset |
| `next_preset` / `previous_preset` | — | preset suivant / précédent dans `order` |
| `toggle_effect` | `target` | inverse le bypass |
| `set_effect_enabled` | `target`, `enabled` | force l'état |
| `loop_toggle` / `loop_record` / `loop_play` / `loop_stop` | — | looper de la piste |
| `mute_input` / `unmute_input` | — | mute de la piste |
| `set_input_volume` | `value` ou vélocité/CC | fader de la piste |
| `set_master_volume` | `value` ou vélocité/CC | master |

`input_index` peut être défini au niveau du mapping ou de chaque action. Le
`debounce_ms` par binding évite les doubles déclenchements (un `mode=press` ne
tire qu'au front montant, un `mode=release` au front descendant).

### Persistance et démarrage

- Les profils sont sauvegardés comme les presets, dans
  `/monkey-resonance/saved_midi_maps/<nom>.json`.
- Un exemple prêt à l'emploi est fourni à la racine du repo :
  `triggers.example.json` (profil `bass_board`). Le copier en
  `/monkey-resonance/triggers.json`, ou dans
  `/monkey-resonance/saved_midi_maps/bass_board.json` puis démarrer avec
  `MKR_MIDI_MAP=bass_board`.
- Au démarrage, l'ordre de priorité est : `MKR_MIDI_CONFIG` (chemin explicite)
  → `MKR_MIDI_MAP` (nom de profil) → `/monkey-resonance/triggers.json`.
- Le preset de démarrage vient de `MKR_START_PRESET`, sinon de
  `startup_preset` du mapping. Un preset introuvable est seulement journalisé.
- Les modifications faites à chaud (`add_midi_binding`, `update_midi_binding`,
  `configure_midi_map` / `PATCH /midi/map` pour l'ordre, le device, le canal ou
  l'`input_index`) restent en mémoire tant qu'on n'appelle pas
  `save_midi_map`.

### Apprendre et simuler sans pédale

- `start_midi_learn()` capture le **premier** message suivant sans
  l'exécuter, puis quitte automatiquement le mode learn (un pad envoie
  souvent Note On + Note Off) ; `stop_midi_learn()` retourne le message
  capturé. On peut ensuite créer le binding avec `add_midi_binding`.
- `simulate_midi_event({"type": "control_change", "channel": 0,
  "controller": 21, "value": 127})` injecte un événement exactement comme le
  ferait le listener. C'est le moyen de valider tout le mapping, le looper et
  les presets avant l'achat du matériel. Pour une simulation, `value` peut être
  omise (127 pour `note_on`/`control_change`) et un `note_on` de valeur 0 est
  normalisé en `note_off`, comme en MIDI réel.
- `performance_status()` / `GET /performance` renvoient le preset courant, le
  mapping, l'état MIDI, le dernier événement et le dernier résultat d'action.

### Thread safety

Le listener MIDI et les serveurs appellent `dispatch_event` depuis leurs
threads. Le contrôleur sérialise ces appels avec un `RLock` et n'accède aux
pistes que par leurs méthodes publiques (qui prennent le lock de la piste).
Le thread audio n'est jamais appelé directement : aucun traitement audio n'est
fait hors de `MixerEngine._audio_loop`.

---

## 7. Enregistrement et analyse

Deux sources, deux sémantiques :

| Mode | Source | Contenu |
| --- | --- | --- |
| `wet=False` (défaut) | file bornée par piste, alimentée par le moteur | **entrée brute de la piste** (1 ou 2 canaux), indépendante du mute |
| `wet=True` | listener global du `MixerEngine` | **mix final des bus** (post-effets, post-mixer, pre-master selon l'ordre interne), muet si le master est mute |

- Le wet n'est **pas** un rejeu de la chaîne en live : c'est la sortie réelle du
  moteur. L'analyse wet est donc cohérente avec ce qui sort des enceintes.
- L'analyse (`get_audio_profile`, `get_rms_level`, `get_pitch_info`,
  `get_frequency_analysis`) est **globale** : elle porte sur la capture
  complète (dry) et sur le mix final (wet), pas sur une piste isolée. Le
  paramètre `index` reste un index de canal de la capture.
- `WET_WARMUP_S = 0.4 s` est attendu avant une mesure wet.
- Les WAV sont écrits en **16 bits, 48 kHz, stéréo**. Certains anciens WAV
  n'ont du signal que sur le canal gauche (legacy).
- `list_recordings` renvoie `duration_s: null` pour de très gros WAV (> 4 Go ou
  échec du module `wave`), sans autre impact.

---

## 7 bis. Scripts d'analyse hors-ligne (`scripts/`)

Trois outils pour analyser les WAV de `records/`, exécutés **dans le
conteneur** avec le venv de l'application (`/opt/venv/bin/python`). Ils lisent
les fichiers hors-ligne et ne touchent pas au moteur audio.

| Script | Rôle |
| --- | --- |
| `scripts/analyze_loops.py` | beat tracking, tempo/mesure, accords par mesure, sections, blocs de mesures répétés et points de coupe alignés (`--max-bars`, `--json`) |
| `scripts/cut_loop.py` | découpe un extrait en WAV avec fondus de 5 ms (`--start`/`--end`, ou `--bars` + `--bpm`) |
| `scripts/remove_silence.py` | retire les silences en streaming (RIFF et **RF64** > 4 Go), avec garde-fous disque et taille (`--threshold-db`, `--min-silence`, `--padding-ms`, `--stats-only`) |

Dépendances : `requirements-analysis.txt` (`librosa==1.0.0`,
`scipy==1.18.1`, `soundfile==0.14.0`), installées dans l'**image de base**
(`Dockerfile`, après `requirements.txt`) et donc héritées par
`Dockerfile.dev`.

```bash
docker exec monkey-resonance-mkr-1 /opt/venv/bin/python \
  /base_app/scripts/analyze_loops.py /monkey-resonance/records/xxx.wav --max-bars 8

docker exec monkey-resonance-mkr-1 /opt/venv/bin/python \
  /base_app/scripts/remove_silence.py /monkey-resonance/records/xxx.wav --stats-only
```

Sans reconstruire l'image, `make analysis-deps` installe les mêmes paquets
dans le conteneur en cours (`uv pip install --python /opt/venv/bin/python`).
Après recréation du conteneur, l'image de base les fournit directement.

Résultat de référence (`record_0_20261107_165722.wav`, 56,02 s) :
**103,4 BPM**, mesure ≈ 2,32 s, motif de **2 mesures répété 11 fois**
(0,09 → 51,41 s, similarité 0,87). Le script de silence a produit
`record_0_20261107_165722_nosilence.wav` : 47,16 s, 34 passages recollés.

---

## 8. Looper

Outils : `play_recording`, `stop_playback`, `playback_status`, `list_recordings`.

- Côté performance, `loop_toggle` fournit le comportement « un seul pad »
  (enregistrer → lire en boucle → arrêter), voir §6 ter.
- **Un looper par piste** : `play_recording(index, …)` joue sur
  `inputs[index]`. Chaque piste a sa propre boucle, indépendante des autres.
- `play_recording(index, filename, loop=True, volume=1.0)` charge un WAV de
  `records/` en mémoire (max **600 s**, garde-fou) et le joue dans la piste.
- Lecture **loop** ou one-shot ; le fichier est mixé avec le live de la piste
  dans le même bloc de sortie → **aucune latence ajoutée**.
- Fondu de **5 ms** en début et fin de boucle (évite le clic).
- Garde-fou de crête : si `wet + boucle > 0.99`, le mix de la piste est atténué.
- Le fader de la piste (`global_volume`) s'applique aussi à la boucle ; le
  volume passé à `play_recording` ne concerne que la boucle.
- La boucle est mixée **après** la chaîne d'effets : elle n'est pas retraitée.
  Le routage, la balance et les gains L/R de la piste s'appliquent ensuite.
- `playback_status(index)` renvoie le fichier, le mode loop, la position et la
  durée de la piste `index`.
- Validation live (ancien moteur mono-piste) : `bass_take3_wet.wav` (30,08 s)
  bouclé à 0,8, position cohérente après 13 s, arrêt propre → temps réel tenu.

---

## 9. Serveur MCP

- Activé **par défaut** au lancement de `main.py` (thread `mcp-server`).
- Transport par défaut : **HTTP streamable**, endpoint `/mcp`
  (`http://<host>:<port>/mcp`). `MCP_TRANSPORT=stdio` force le stdio.
- Port par défaut : **8005** (`MCP_PORT`).
- `--with_api` remplace le MCP (les deux utilisent le même port et sont
  mutuellement exclusifs).

### Outils exposés (61)

| Domaine | Outils |
| --- | --- |
| État / devices | `global_status`, `list_inputs_outputs`, `list_inputs`, `get_input_effects`, `get_mixer` |
| Pistes (mix) | `add_input`, `remove_input`, `set_input_channels`, `set_input_mix`, `set_route`, `mute_input`, `unmute_input` |
| Bus de sortie | `add_output`, `remove_output`, `set_output_channels`, `set_output_volume`, `mute_output`, `unmute_output` |
| Master | `set_master_volume`, `mute_master`, `unmute_master` |
| Effets | `add_effect_to_input`, `update_effect`, `remove_effect_from_input`, `save_input_effects`, `load_input_effects`, `toggle_effect`, `set_effect_enabled` |
| Enregistrement | `start_input_recording`, `stop_input_recording`, `list_recordings` |
| Looper | `play_recording`, `stop_playback`, `playback_status`, `loop_toggle`, `loop_record`, `loop_play`, `loop_stop` |
| Presets / performance | `list_presets`, `load_preset`, `next_preset`, `previous_preset`, `performance_status` |
| MIDI | `list_midi_devices`, `get_midi_status`, `list_midi_maps`, `get_midi_map`, `configure_midi_map`, `save_midi_map`, `load_midi_map`, `add_midi_binding`, `update_midi_binding`, `remove_midi_binding`, `simulate_midi_event`, `start_midi_learn`, `stop_midi_learn`, `get_midi_learn` |
| Analyse | `get_audio_profile`, `get_rms_level`, `get_pitch_info`, `get_frequency_analysis` |

Un prompt MCP `help` rappelle l'usage général des outils.

Détails utiles :

- `inputs` contient **une piste par input logique** (par défaut `input_0`,
  `input_1`, …). Le paramètre `index` des outils effets, mute, volume et
  looper cible donc une piste précise.
- `get_mixer` renvoie l'état complet : pistes (canaux, fader, balance, gains
  L/R, routes), bus (canaux physiques, volume, mute), master et latence.
- `set_input_mix(index, volume, balance, left_gain, right_gain)` : les
  paramètres omis restent inchangés. `balance` ∈ [−1, +1].
- `set_route(input_index, output_index, volume)` règle l'envoi d'une piste
  vers un bus. Un nouvel input est routé à 1.0 vers le bus 0, 0.0 ailleurs ;
  un nouveau bus ne reçoit rien par défaut.
- Les tools d'analyse acceptent `wet=True` pour analyser le **mix final**
  (et non une piste isolée).
- `set_output_volume` cible désormais un **bus** logique, plus un canal
  gauche/droite.
- `toggle_effect` / `set_effect_enabled` acceptent une position ou un chemin
  d'effet ; `input_index` par défaut = 0.
- `loop_*` ciblent la piste `input_index` (défaut 0) ; `loop_toggle` est le
  comportement « un seul pad ».
- `add_midi_binding(source, action)` valide immédiatement le format ; en cas
  d'erreur, le tool renvoie `{"error": ...}` sans modifier le mapping.
- `configure_midi_map({"order": [...], "channel": 0, ...})` met à jour les
  métadonnées du mapping actif sans toucher aux bindings (sauf si
  `bindings` est fourni).
- `simulate_midi_event` est le moyen de test sans pédale : il passe par le
  même chemin que le listener (debounce et learn compris).

---

## 10. API REST (alternative)

Lancée avec `python main.py --with_api` ; documentation interactive sur
`/docs`. Même port que le MCP. Routes historiques :

| Méthode | Route |
| --- | --- |
| GET | `/global_status` |
| GET | `/list_inputs_outputs` |
| GET | `/list_inputs` |
| GET | `/list_effects/{index}` |
| POST | `/mute_input/{index}` |
| POST | `/unmute_input/{index}` |
| POST | `/add_effect_to_input/{index}` |
| POST | `/update_effect/{index}` |
| POST | `/remove_effect_from_input/{index}` |
| POST | `/start_input_recording/{index}` |
| POST | `/stop_input_recording/{index}` |

Routes mixer :

| Méthode | Route | Rôle |
| --- | --- | --- |
| GET | `/mixer` | état complet du mixer |
| POST | `/mixer/inputs` | créer une piste (`name`, `channels`) |
| DELETE | `/mixer/inputs/{index}` | retirer une piste |
| PATCH | `/mixer/inputs/{index}/channels` | changer les canaux captés |
| PATCH | `/mixer/inputs/{index}/mix` | fader, balance, gains L/R |
| PATCH | `/mixer/routes` | volume d'envoi input → output |
| POST | `/mixer/outputs` | créer un bus (`name`, canaux) |
| DELETE | `/mixer/outputs/{index}` | retirer un bus |
| PATCH | `/mixer/outputs/{index}/channels` | changer le mapping physique |
| PATCH | `/mixer/outputs/{index}/volume` | volume du bus |
| POST | `/mixer/outputs/{index}/mute` | mute du bus |
| POST | `/mixer/outputs/{index}/unmute` | unmute du bus |
| PATCH | `/mixer/master` | volume master |
| POST | `/mixer/master/mute` | mute master |
| POST | `/mixer/master/unmute` | unmute master |

Routes performance / MIDI :

| Méthode | Route | Rôle |
| --- | --- | --- |
| GET | `/presets` | liste, ordre et preset courant |
| GET | `/presets/current` | preset courant |
| POST | `/presets/next` | preset suivant |
| POST | `/presets/previous` | preset précédent |
| POST | `/presets/{name}` | charge un preset précis |
| GET | `/performance` | état complet (preset, mapping, MIDI, learn) |
| POST | `/effects/{index}/toggle` | inverse le bypass d'un effet |
| POST | `/effects/{index}/enabled` | force l'état d'un effet |
| POST | `/looper/{index}/toggle` | pad unique enregistrer/lire/arrêter |
| POST | `/looper/{index}/record` | démarre un enregistrement |
| POST | `/looper/{index}/play` | lit la dernière boucle |
| POST | `/looper/{index}/stop` | arrête la boucle |
| GET | `/midi/devices` | devices raw MIDI visibles |
| GET | `/midi/status` | connexion, dernier événement, learn |
| GET | `/midi/maps` | profils sauvegardés |
| GET | `/midi/map` | mapping actif |
| PATCH | `/midi/map` | métadonnées du mapping (ordre, device, channel, …) |
| POST | `/midi/maps/{name}/save` | sauvegarde le mapping actif |
| POST | `/midi/maps/{name}/load` | charge un profil |
| POST | `/midi/bindings` | ajoute un binding |
| PATCH | `/midi/bindings/{id}` | modifie un binding |
| DELETE | `/midi/bindings/{id}` | supprime un binding |
| POST | `/midi/simulate` | injecte un événement MIDI |
| POST | `/midi/learn/start` | démarre l'apprentissage |
| POST | `/midi/learn/stop` | arrête et retourne le message capturé |
| GET | `/midi/learn` | état de l'apprentissage |

L'API REST expose désormais le looper et la performance ; seule l'**analyse**
reste spécifique au MCP. C'est une dette connue (voir plus bas).

---

## 11. Lancement et commandes

### Docker / Makefile

```bash
make build          # image monkey-resonance-pedalboard:latest
make build-dev      # image dev (pytest, ruff, opencode)

make run            # moteur interactif (MCP activé par défaut)
make run-mcp        # service en arrière-plan (MCP activé par défaut)
make run-api        # API REST à la place du MCP (/docs)
make up             # démarre le service en arrière-plan
make down           # arrête et supprime le service

make test           # pytest tests/ app/
make lint           # ruff check app/

make dev-deps       # pytest/ruff dans le conteneur en cours
make analysis-deps  # librosa/scipy/soundfile dans le conteneur en cours

make shell          # bash dans l'image prod
make shell-dev      # bash dans l'image dev
```

### Directement dans le container

```bash
cd /base_app/app
python main.py                  # moteur + MCP (port 8005)
python main.py --with_api       # moteur + API REST (/docs)
python main.py --list-devices   # liste les devices puis quitte
python main.py --buffer-size 64 --sample-rate 48000
```

### Agent OpenCode (container)

```bash
make agent-serve    # démarre le devcontainer + le serveur OpenCode (4096)
make agent-host     # TUI hôte connectée au serveur du container
make agent          # TUI directement dans le container
```

---

## 12. Vérifications réalisées

Dernière vérification complète (2026-11-09, après ajout du contrôle de
performance et du MIDI) :

- `make lint` → **All checks passed** (ruff sur `app/`).
- `make test` → **116 passed, 2 skipped**, dont les tests dédiés au
  contrôleur et au MIDI :
  - `tests/test_performance.py` : presets, conservation du volume, bypass,
    looper « un seul pad », CRUD de mappings, dispatch Program Change/CC/Note,
    mode apprendre, refus des bindings invalides, et câblage réel des routes
    REST et des tools MCP sur le contrôleur ;
  - `tests/test_midi_control.py` : Program Change, CC, Note On/Off, vélocité 0,
    running status, SysEx/horloge ignorés, messages incomplets ;
  - résolution du device : index de carte et repli sur le premier raw MIDI
    quand `/proc/asound` n'est pas exposé dans le container.
- Ouverture réelle de `/dev/snd/midiC0D0` validée dans un conteneur : listener
  `connected=True`, puis arrêt propre (aucun message sans pédale branchée).
- Le reste de la suite couvre le mixer (`tests/test_mixer.py`), les effets,
  le looper, l'analyse et les devices.
- Analyse hors-ligne : `ruff check` propre sur `scripts/analyze_loops.py`,
  `scripts/cut_loop.py` et `scripts/remove_silence.py` ; les trois scripts ont
  été relancés dans le conteneur avec `/opt/venv/bin/python` (tempo 103,4 BPM,
  34 passages de silence, découpe de boucle OK).
- Image de base reconstruite (`make build`) : dans un conteneur jetable,
  `import librosa, scipy, soundfile` → 1.0.0 / 1.18.1 / 0.14.0, et
  `scripts/` présent sur `/base_app`.
- `python main.py --list-devices` → devices détectés, dont l'AudioBox USB 96
  en « Direct hardware device without any conversions ».
- Démarrage réel validé : `MixerEngine` avec **2 pistes** (`input_0` canal 0,
  `input_1` canal 1) et **1 bus** `main` (0,1), capture 128 frames, latence
  ≈ **5,33 ms**.
- Outils MCP : **61 outils** enregistrés (vérifié par
  `tests/test_smoke_imports.py`). Le dernier test HTTP complet avant l'ajout
  performance/MIDI avait listé 36 outils et validé `get_mixer`, `add_input`,
  `set_input_mix`, `set_route`, `set_output_volume` et `add_output` sans
  erreur ; les nouveaux tools sont couverts par le test d'enregistrement.
- Live historique (moteur mono-piste) : enregistrement wet 8,12 s écrit en
  8,12 s ; dry 8,62 s sur ~8,7 s ; boucle 30,08 s lue et bouclée en temps réel.
- Aucun import `pyo` restant dans `app/` ni `scripts/`.

Les tests marqués *skipped* sont liés à l'environnement (accès audio live non
activé par défaut), pas à une régression.

---

## 13. État des conteneurs

Au moment de la dernière vérification :

| Conteneur | Image | État |
| --- | --- | --- |
| `monkey-resonance-mkr-1` | `monkey-resonance-pedalboard:latest` (reconstruite avec les deps d'analyse) | **en marche**, MCP sur `:8005`, 2 pistes, 1 bus, latence 5,33 ms |
| `mkr-pedalboard-mcp` | `monkey-resonance-pedalboard:latest` | arrêté (0), monté sur le worktree `exp/spotify-pedalboard` |
| `monkey-resonance-pyo` | ancienne image pyo | arrêté (137) |

**Important** : `mkr-pedalboard-mcp` montait le worktree expérimental, pas le
`main` fusionné. Pour reprendre sur `main`, il faut recréer le conteneur depuis
`/home/ubuntu/projets/monkey-resonance` (voir la procédure ci-dessous).

---

## 14. Limites connues et points d'attention

1. **Pas de synthèse** : Pedalboard traite l'entrée, il ne génère pas de son.
   Le mixer route des signaux captés ; un instrument génératif nécessiterait
   un autre moteur.
2. **Carte son exclusive** : la capture directe ne permet pas de deuxième
   client. Tout ce qui a besoin du signal doit passer par le moteur.
3. **Busy-wait** : `AudioStream.write()` peut occuper le thread audio à
   20–99 % d'un cœur selon l'instant ; température du Pi ~55–58 °C.
4. **Pertes d'entrée** : `read()` de Pedalboard remet `numDroppedInputFrames`
   à zéro ; les pertes sont estimées via l'horloge murale, pas comptées
   directement.
5. **Pas de séparation moteur / serveurs** : le MCP et l'API appellent le
   moteur via `sys.modules["__main__"]` et son lock. La séparation en
   « Control API » décrite dans `PLAN_SEPARATION_MCP.md` n'est pas implémentée.
6. **Duplication API/MCP** : `app/monkey_api/api.py` et `app/server/server.py`
   restent proches ; le MCP a plus d'outils (looper, analyse).
7. **`duration_s: null`** possible sur les très gros WAV.
8. **WAV legacy** parfois mono-canal (gauche uniquement).
9. **MCP et API sur le même port** : impossibles à lancer ensemble.
10. **Coût CPU proportionnel aux pistes** : chaque piste traverse sa chaîne
    d'effets à chaque bloc, même muette (le mute coupe le signal, pas le
    traitement). Avec beaucoup de pistes, réduire les effets ou la taille de
    bloc est le levier.
11. **Une piste est toujours stéréo en sortie** : une piste mono est dupliquée
    gauche/droite avant balance/gains, puis routée. Deux bus qui pointent vers
    les mêmes canaux physiques se somment (pas de déduplication).
12. **Config du mixer non persistée** : `AUDIO_INPUTS` / `AUDIO_OUTPUTS` sont
    lus au démarrage ; les changements faits par MCP/REST sont perdus au
    redémarrage. Les chaînes d'effets se rechargent séparément.
13. **Analyse globale, pas par piste** : l'analyseur voit la capture complète
    (dry) et le mix final (wet). Pour analyser une piste isolée, passer par
    son enregistrement dry.
14. **MIDI matériel non validé** : l'ouverture de `/dev/snd/midiC0D0` et le
    parseur ont été testés, mais aucune pédale physique n'est disponible pour
    valider les messages réels, les canaux et le ressenti (debounce, LED).
    Utiliser `simulate_midi_event` en attendant.
15. **Device MIDI exclusif** : le listener raw MIDI occupe le device ; couper
    `MKR_MIDI=0` avant d'utiliser `amidi -d` ou un autre client.
16. **Mappings non persistés automatiquement** : les changements faits à chaud
    via MCP/REST sont perdus au redémarrage s'ils n'ont pas été sauvegardés
    avec `save_midi_map`. Le mapping actif est rechargé par
    `MKR_MIDI_CONFIG`, `MKR_MIDI_MAP` ou `triggers.json`.

---

## 15. Procédure de reprise

Depuis l'hôte, racine du repo (`/home/ubuntu/projets/monkey-resonance`) :

```bash
# 0. Vérifier l'état Git
git status --short --branch
git log --oneline -3          # attendu : dd64bef

# 1. S'assurer que l'AudioBox est libre
docker ps -a --format '{{.Names}}\t{{.Status}}' | grep -Ei 'mkr|monkey'

# 2. Reconstruire / démarrer sur main
make build                    # si l'image doit être actualisée
make up                       # service en arrière-plan, MCP sur 8005
# ou, pour l'atelier de dev :
make build-dev
make up-dev

# 3. Vérifier
make test
make lint
curl -s http://localhost:8005/mcp   # le MCP répond (HTTP streamable)

# 4. Vérifier le mixer et recharger la chaîne de référence (perdue au
#    redémarrage). Via MCP :
#      get_mixer()
#      load_input_effects(0, "bass_clear_warm_punch")
#    (ou via l'API REST : GET /mixer, puis les routes /mixer/...)
#
#    Pour la performance, le preset et le mapping peuvent être automatiques :
#      MKR_START_PRESET=bass_clear_warm_punch \
#      MKR_MIDI_MAP=bass_board make up
#    Sans matériel, tester avec simulate_midi_event / POST /midi/simulate.

# 5. Ouvrir l'agent OpenCode si besoin
make agent-serve
make agent-host
```

Redémarrer le container de dev puis l'app avec MCP :

```bash
make up-dev
make app        # démarre/redémarre python main.py --with_mcp dans le container
```

En cas de port occupé : `scripts/check-ports.sh` ou `MKR_PORT=8011 make up`.

---

## 16. Dettes / documents à mettre à jour

- `PLAN_SEPARATION_MCP.md` : marqué obsolète en tête de fichier ; décrit encore
  pyo, `app/monkey_mcp/mcp.py` et une séparation non implémentée. À réécrire ou
  archiver.
- `AGENTS.md` : actualisé pour Pedalboard et le mixer multi-pistes ; le contrat
  `sys.modules["__main__"]` reste la règle.
- API REST : ajouter l'analyse, ou fusionner avec le MCP en une Control API
  unique. La performance et le looper y sont désormais présents.
- MIDI : valider sur matériel réel (pédale branchée sur l'AudioBox), puis
  figer un profil `saved_midi_maps/` de référence. Le retour d'état (LED,
  afficheur) n'est pas géré.
- Persistance du mixer : `AUDIO_INPUTS` / `AUDIO_OUTPUTS` sont statiques. Un
  fichier de config (ou une sauvegarde via MCP) éviterait de reconfigurer les
  pistes et bus à chaque redémarrage.
- `make run-prod-mcp` : la cible lance `main.py` (MCP par défaut), mais le nom
  et le commentaire méritent une clarification.
- Anciens scripts/services systemd pyo (`Pyo-server`, `.devcontainer/etc`) :
  vestiges à nettoyer si non utilisés.
