# Expérience — Pedalboard (Spotify) à la place de pyo

Branche `exp/spotify-pedalboard`, basée sur `main` @ `c19c2c8`.

État au 2026-11-04 : image `monkey-resonance-pedalboard:latest` reconstruite,
tests hors-ligne et live validés (voir ci-dessous). Capture directe à 128
frames, looper et analyse alimentés par le moteur.

## Objectif

Évaluer si **Pedalboard** peut remplacer `pyo` pour la chaîne d'effets temps
réel de Monkey Resonance, avec une meilleure maintenabilité et sans dégrader la
latence.

## Mise au point sur le nom

Spotify ne publie pas de « DAW framework » Python. Le projet visé est
**Pedalboard** (GPLv3, basé sur JUCE) : I/O audio, effets, hébergement de
plugins VST3/AU. Ce n'est **pas** un DAW : pas de séquenceur, pas de transport,
pas de synthèse ni d'objets générateurs comme pyo.

## Vérifié le 2026-10-31

### Hors container (hôte)

- `pedalboard 0.9.26` s'installe depuis PyPI (wheel Linux x86_64) et traite un
  buffer stéréo 48 kHz hors-ligne : `Gain → Delay → Reverb` OK.
- `AudioStream` expose `input_device_names` / `output_device_names` et voit
  l'AudioBox USB 96 (ALSA/PipeWire) sur l'hôte.
- `AudioStream` est supporté sur Linux depuis 0.9.14 ; `read()` permet de
  capturer l'entrée, `plugins` traite l'audio entrant → sortant.

### Live dans le container dev (AudioBox libérée)

Le container pyo `monkey-resonance-mkr-run-f428a266bec5` a été arrêté le temps
des mesures, puis un container équivalent `monkey-resonance-pyo` a été relancé
(`docker compose run -d --service-ports --name monkey-resonance-pyo mkr python
main.py --with_mcp`).

- Entrée **et** sortie résolues automatiquement sur le device matériel direct
  de l'AudioBox (`Direct hardware device without any conversions`), qui évite
  PipeWire/Pulse et la période du dsnoop (1024 frames).
- `RUN_AUDIO_TESTS=1 pytest tests/test_audio_box_detection.py` : **5 tests
  passés** (ouverture, mute, sample rate, buffer, enregistrement live).
- `python detect-sc.py --test` (sortie muette) : 48 kHz, **128 frames**,
  3,3 % CPU, 0 frame d'entrée perdue.
- Chaîne complète (compresseur → disto → HP → LP → biquad → chorus) à
  **64 frames / 48 kHz** pendant 10 s : 0 frame perdue, 4,8 % CPU.
- `main.py --with_api` avec `AUDIO_START_MUTED=1` : device ouvert, API sur
  `/docs`, `/global_status` → `true`, `/list_inputs` OK, ajout / mise à jour /
  liste / suppression d'effets OK, enregistrement de 1,5 s via l'API
  (71 680 frames, 1,493 s, stéréo 48 kHz), arrêt propre sur SIGTERM (code 0).
- Toutes les chaînes sauvegardées (`blink_test1`, `blinktest2`, `blinktest3`)
  se chargent et se traitent sans device.

| Buffer | Latence buffer A/R | CPU | Frames perdues |
| --- | --- | --- | --- |
| 128 (défaut) | 5,33 ms | 3,3 % | 0 |
| 64 | 2,67 ms | 4,8 % | 0 |

**Choix par défaut** : buffer **128 frames** (5,33 ms A/R logiciel) pour garder
une marge sous charge (MCP/API, effets), avec `AUDIO_BUFFER_SIZE=64` validé et
documenté pour la latence minimale.

**Non mesuré** : latence analogique réelle (ADC + USB + DAC). La valeur
ci-dessus est la latence logicielle du buffer ; `AudioStream` n'expose pas la
latence matérielle de JUCE.

**Enregistrement et analyse** : Pedalboard ne remplit pas le FIFO de capture
quand le stream a aussi une sortie, et la carte est désormais ouverte en
exclusif sur le device matériel direct. L'enregistrement et l'analyse ne
peuvent donc plus ouvrir leur propre capture : ils sont **alimentés par le
moteur** (listener + file bornée). Le thread audio ne fait qu'un
`put_nowait` : si le consommateur est en retard, le bloc est ignoré au lieu de
bloquer le jeu. C'est ce qui garantit qu'une boucle ou une analyse n'ajoute
**aucune latence** au live.

Latence logicielle mesurée : capture **128 frames (2,67 ms)** + sortie
**128 frames (2,67 ms)** ≈ **5,4 ms** aller-retour, sans surcoût quand une
boucle joue (le mix se fait dans le même bloc). L'ancien moteur C++ duplex
était à 2,7 ms, mais son entrée dsnoop était déjà à ~21 ms.

## Configuration

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `AUDIO_INPUT_DEVICE` | auto (AudioBox direct) | nom exact, sous-chaîne ou index |
| `AUDIO_OUTPUT_DEVICE` | auto (AudioBox direct) | idem |
| `AUDIO_RECORD_DEVICE` | = entrée | conservé ; l'enregistrement vient du moteur |
| `AUDIO_SAMPLE_RATE` | `48000` | sample rate |
| `AUDIO_BUFFER_SIZE` | `128` | frames par buffer |
| `AUDIO_INPUT_CHANNELS` | `2` | canaux d'entrée |
| `AUDIO_OUTPUT_CHANNELS` | `2` | canaux de sortie |
| `AUDIO_START_MUTED` | `0` | démarre muet (sécurité larsen) |
| `AUDIO_GLOBAL_VOLUME` | `1.0` | gain global linéaire |
| `AUDIO_ALLOW_FEEDBACK` | `0` | autorise le feedback JUCE |

## Correspondance pyo → Pedalboard

| pyo | Pedalboard |
| --- | --- |
| `pyo.Input(i)` | `AudioStream(input_device_name=..., output_device_name=...)` |
| `pyo.Chorus`, `Delay`, `Reverb`… | `Chorus`, `Delay`, `Reverb`… |
| `CustomDelay(pyo.PyoObject)` | `Delay` natif, ou plugin VST3 |
| `pyo.Record(output)` | tap du moteur (file bornée + listener), dry ou wet post-effets |
| Chaîne `PyoObject` / `setInput` | `Pedalboard([...])` mutable (`append`, `del`, paramètres) |
| Serveur pyo + `s.boot()` | pas d'équivalent : le stream gère le device |

## Limites et état de l'implémentation

1. **Pas de synthèse** : si l'app doit générer des sons (et pas seulement
   traiter l'entrée), pyo reste nécessaire. Aujourd'hui `main.py` ne crée que
   des `Input`, donc le périmètre est compatible.
2. **Enregistrement post-effets** : le dry est capté par le moteur, et le wet
   est la **sortie réelle post-effets** fournie par le même listener (avant mix
   de la boucle). Plus besoin de rejouer la chaîne ni d'ouvrir une capture
   secondaire.
3. **Latence** : un bloc de capture (128 frames, 2,7 ms) + un bloc de lecture
   (128 frames, 2,7 ms) ≈ **5,4 ms** logiciels. La capture directe délivre le
   débit réel à 128 frames, contrairement au dsnoop (17 % à 128, calé sur sa
   période de 1024). La boucle est mixée dans le même bloc : elle n'ajoute
   **aucune** latence pendant le jeu.
4. **Licence GPLv3** : le repo n'a pas de LICENSE. Si une diffusion non-GPL
   est prévue, c'est bloquant.
5. **Contrat `sys.modules["__main__"]` — conservé** : `main.py` expose
   `AudioStream`, `audio_devices` et `inputs`. L'adaptateur garde l'API
   (`add_effect`, `remove_effect`, `update_effect`, `start`, `stop`, `close`,
   `save_effects`, `load_effects`, `start_recording`, `stop_recording`,
   `global_volume`, `play_recording`, `stop_playback`).
6. **Thread-safety** : le traitement des effets et le mixage tournent dans un
   thread audio dédié ; les mutations de chaîne sont sérialisées par un verrou
   et ne font que remplacer l'objet `Pedalboard` utilisé au bloc suivant.
   L'enregistrement écrit dans une file bornée consommée par un thread dédié :
   le thread audio ne fait qu'un `put_nowait`, jamais d'I/O disque.
7. **Formats sauvegardés — compatibilité** : `saved_effects/*.json` (chemins
   pyo) est traduit par `libs/effect_lib.py` ; les nouvelles sauvegardes
   portent `"engine": "pedalboard"`. Les formats liste (ancien) et dict
   (nouveau) sont acceptés.
8. **Un seul stream stéréo** : Pedalboard n'expose pas de chaîne par canal ;
   `inputs` contient donc un unique `AudioStream` (index 0) en 2 in / 2 out.
   Le moteur ouvre en fait **deux** streams Pedalboard (capture seule +
   lecture seule) : un stream duplex ignore le buffer d'écriture, donc le
   mixage live + boucle se fait côté Python. L'enregistrement et l'analyse sont
   des listeners du moteur, pas des captures supplémentaires.

## Implémentation

- `app/libs/audio_devices.py` : découverte JUCE, résolution par nom/index,
  entrée et sortie auto sur le device matériel direct, configuration par
  variables d'env.
- `app/libs/audio_stream.py` : moteur du looper. Deux streams Pedalboard
  (capture matérielle seule, lecture matérielle seule), un thread audio qui
  traite les blocs (`reset=False`), applique le gain/mute, mixe la boucle en
  cours et écrit la sortie. Chaîne d'effets, `save_effects`/`load_effects`,
  enregistrement via une file bornée, listeners `(dry, wet)` pour l'analyse.
- `app/libs/effect_lib.py` : mapping pyo → Pedalboard, `CustomDelay`,
  `EffectSlot`, chemins natifs `pedalboard.Classe`.
- `app/libs/music_analysis.py` : analyse temps réel numpy (RMS, pitch,
  spectre), alimentée par le **listener du moteur** (file bornée + thread
  d'analyse) ; remplace l'analyseur pyo.
- `app/main.py` : point d'entrée, threads API/MCP, arrêt propre SIGINT/SIGTERM.
- `app/detect-sc.py` : liste les devices et teste le stream (muet par défaut).
- Tests : `tests/test_audio_devices.py`, `test_effects.py`,
  `test_audio_stream_offline.py` (sans device), `test_music_analysis.py` ;
  `test_audio_box_detection.py` (live, `RUN_AUDIO_TESTS=1`, dont
  l'enregistrement).

## Analyse audio (MCP)

Les outils d'analyse de `main` sont portés sur Pedalboard, sans pyo :

| Tool | Résultat |
| --- | --- |
| `get_rms_level(index, window_size, wet)` | RMS, peak, dBFS, présence de signal |
| `get_pitch_info(index, wet)` | fréquence (autocorrélation), note MIDI, nom, confiance |
| `get_frequency_analysis(index, fft_size, wet)` | dominante, centroïde, bandes, 5 pics |
| `get_audio_profile(index, wet)` | RMS + pitch + note + dominante |
| `set_output_volume(index, volume)` | gain de sortie (les 2 canaux) |
| `save_input_effects(index, name)` | sauvegarde la chaîne dans `saved_effects/<name>.json` |
| `load_input_effects(index, name)` | recharge une chaîne sauvegardée |
| `start_input_recording(index, filename, wet)` | enregistre l'entrée (wet=false) ou la sortie (wet=true) |
| `stop_input_recording(index, wet)` | arrête l'enregistrement correspondant |

### Signal dry et signal wet

Le moteur appelle ses listeners à chaque bloc avec deux signaux :

- **dry** (`wet=false`, défaut) : l'entrée brute du bloc, telle que captée —
  c'est ce qu'enregistre `start_input_recording` ;
- **wet** (`wet=true`) : la **sortie réelle post-effets** du même bloc (avant
  mix de la boucle), donc exactement ce qui part vers la carte.

Le listener ne fait qu'un `put_nowait` dans une file bornée ; un thread
d'analyse consomme la file et alimente les ring buffers de 4 s (dry et wet).
Si l'analyse prend du retard, les blocs en trop sont ignorés : le thread audio
n'attend jamais et le jeu live ne gagne aucune latence.

`WetPath` (rejeu de la chaîne sur le dry) reste utilisé en mode hors-ligne
(tests, ou moteur sans `add_listener`) ; il n'est plus sollicité en live.

`index` désigne le **canal d'entrée** (0 = gauche, 1 = droite). Pedalboard
n'expose pas de gain par canal : `set_output_volume` applique le gain au
stream stéréo, l'index est conservé pour compatibilité.

Seuil de signal : −60 dBFS (bruit de fond de l'AudioBox ignoré). Pitch :
50–2000 Hz. Validé live : analyse et enregistrement simultanés, sans capture
supplémentaire.

## Looper intégré

Le moteur peut relire un WAV de `records/` en boucle, mixé avec le live
(`play_recording`, `stop_playback`, `playback_status`). Le buffer est chargé en
mémoire (limite `MAX_LOOP_SECONDS`, 600 s), avec un fondu de 5 ms aux bords et
un volume par boucle.

- la boucle est mixée **dans le même bloc** que le live, après la chaîne
  d'effets (elle n'est pas retraitée) : aucun buffer supplémentaire, **aucune
  latence ajoutée** ;
- garde-fou de crête (0,99) qui atténue seulement en cas de saturation ;
- l'état (fichier, boucle, volume, position) est exposé par
  `playback_status`.

Testé live : `bass_take3_wet.wav` (30,08 s) bouclé à volume 0,8 pendant ~18 s,
position 17,7 s (100 % temps réel), arrêt propre, ~99 % d'un cœur (busy-wait
d'écriture de `AudioStream`, pas le looper), 57 °C.

## MCP en HTTP streamable (MCP 2.x)

Le serveur MCP n'est plus en stdio : `start_mcp()` utilise `MCPServer.run(
transport="streamable-http", host=..., port=...)`, endpoint par défaut
**`/mcp`**. `MCP_TRANSPORT=stdio` reste disponible pour les clients qui
lancent eux-mêmes le process.

```bash
# Serveur MCP (moteur audio + HTTP dans le même process)
MCP_PORT=8011 docker compose run --rm --service-ports mkr \
  python main.py --with_mcp
# → http://localhost:8011/mcp

# Côté opencode (opencode.jsonc)
# "monkey-resonance": { "type": "remote", "url": "http://localhost:8005/mcp" }
```

Validé bout-en-bout le 2026-11-01 avec MCP 2.3.0 : 11 tools exposés,
`global_status=true`, ajout/maj/liste/suppression d'effet, mute/unmute et
enregistrement (57 344 frames, 1,195 s) via
`mcp.client.streamable_http.streamable_http_client`. Le transport stdio a
aussi été rejoué avec la même version.

## Lancer ce worktree en parallèle

L'image de cette branche est taguée **`monkey-resonance-pedalboard:latest`**
(image dev : **`monkey-resonance-pedalboard-dev:latest`**) : construire/la
lancer ne remplace pas les images pyo de `main`.

```bash
# 1. Construire l'image Pedalboard
make build

# 2. Libérer l'AudioBox et le port 8005 : arrêter le process pyo qui les
#    tient (container dev `monkey-resonance-mkr-1` ou `monkey-resonance-pyo`).
docker stop monkey-resonance-pyo   # si ce container temporaire existe

# 3. API sur http://localhost:8011/docs
MKR_PORT=8011 docker compose run --rm --service-ports mkr \
  python main.py --with_api

# 4. Relancer pyo si nécessaire
docker start monkey-resonance-pyo
```

Le compose monte `.:/code` et `${MKR_DATA:-/home/ubuntu/monkey-resonance}` sur
`/monkey-resonance` (records/saved_effects partagés avec l'hôte).

`pwd` doit être la racine de ce worktree : le conteneur exécute alors bien le
code de la branche. L'autre worktree utilise `8012`, le repo principal garde
`8005`.
