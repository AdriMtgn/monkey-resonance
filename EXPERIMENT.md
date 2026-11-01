# Expérience — Pedalboard (Spotify) à la place de pyo

Branche `exp/spotify-pedalboard`, basée sur `main` @ `c19c2c8`.

État au 2026-11-01 : image `monkey-resonance-pedalboard:latest` reconstruite,
tests hors-ligne et live validés (voir ci-dessous).

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

- Entrée résolue automatiquement sur le device **dsnoop** de l'AudioBox
  (`Direct sample snooping device`), sortie sur le device matériel direct
  (`Direct hardware device without any conversions`). Le dsnoop permet une
  seconde capture simultanée pour l'enregistrement ; la sortie évite
  PipeWire/Pulse.
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

**Enregistrement** : Pedalboard ne remplit pas le FIFO de capture quand le
stream a aussi une sortie. On ouvre donc une **seconde capture input-only sur
le dsnoop** pendant que le stream principal tourne. Elle enregistre l'entrée
brute (pre-effets), pas la sortie. Testé live : 2 captures dsnoop simultanées,
0 frame perdue sur 3 s et sur 1,5 s via l'API.

## Configuration

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `AUDIO_INPUT_DEVICE` | auto (dsnoop AudioBox) | nom exact, sous-chaîne ou index |
| `AUDIO_OUTPUT_DEVICE` | auto (AudioBox direct) | idem |
| `AUDIO_RECORD_DEVICE` | = entrée | capture de l'enregistrement (dsnoop conseillé) |
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
| `pyo.Record(output)` | 2e capture dsnoop (entrée brute, **pas** la sortie post-effets) |
| Chaîne `PyoObject` / `setInput` | `Pedalboard([...])` mutable (`append`, `del`, paramètres) |
| Serveur pyo + `s.boot()` | pas d'équivalent : le stream gère le device |

## Limites et état de l'implémentation

1. **Pas de synthèse** : si l'app doit générer des sons (et pas seulement
   traiter l'entrée), pyo reste nécessaire. Aujourd'hui `main.py` ne crée que
   des `Input`, donc le périmètre est compatible.
2. **Enregistrement post-effets — limite assumée** : la capture secondaire
   dsnoop enregistre l'entrée brute, pas la sortie post-effets. Un tap de sortie
   nécessiterait un moteur externe (JACK/ALSA loopback) ; `pedalboard.Plugin`
   ne peut pas être sous-classé en Python.
3. **Latence** : réglable par `AUDIO_BUFFER_SIZE` ; mesurée jusqu'à 64 frames
   (2,67 ms A/R logiciel) sans frame perdue sur l'AudioBox. Pas de garantie
   temps réel dure (JUCE + thread interne), d'où le défaut à 128 frames.
4. **Licence GPLv3** : le repo n'a pas de LICENSE. Si une diffusion non-GPL
   est prévue, c'est bloquant.
5. **Contrat `sys.modules["__main__"]` — conservé** : `main.py` expose
   `AudioStream`, `audio_devices` et `inputs`. L'adaptateur garde l'API
   (`add_effect`, `remove_effect`, `update_effect`, `start`, `stop`, `close`,
   `save_effects`, `load_effects`, `start_recording`, `stop_recording`,
   `global_volume`).
6. **Thread-safety** : les mutations de chaîne sont sérialisées par un verrou
   côté control thread ; JUCE applique les changements via son propre polling.
   Ne pas muter la chaîne directement depuis FastAPI/MCP : passer par
   `AudioStream`.
7. **Formats sauvegardés — compatibilité** : `saved_effects/*.json` (chemins
   pyo) est traduit par `libs/effect_lib.py` ; les nouvelles sauvegardes
   portent `"engine": "pedalboard"`. Les formats liste (ancien) et dict
   (nouveau) sont acceptés.
8. **Un seul stream stéréo** : Pedalboard n'expose pas de chaîne par canal ;
   `inputs` contient donc un unique `AudioStream` (index 0) en 2 in / 2 out.
   L'enregistrement ouvre en plus une capture input-only dsnoop (pas exposée
   dans `inputs`).

## Implémentation

- `app/libs/audio_devices.py` : découverte JUCE, résolution par nom/index,
  entrée auto sur le device partageable `dsnoop`, sortie auto sur le device
  matériel direct, configuration par variables d'env.
- `app/libs/audio_stream.py` : wrapper `pedalboard.io.AudioStream`, chaîne
  d'effets, mute (`stop`), fermeture (`close`), volume global, enregistrement
  via une seconde capture dsnoop.
- `app/libs/effect_lib.py` : mapping pyo → Pedalboard, `CustomDelay`,
  `EffectSlot`, chemins natifs `pedalboard.Classe`.
- `app/main.py` : point d'entrée, threads API/MCP, arrêt propre SIGINT/SIGTERM.
- `app/detect-sc.py` : liste les devices et teste le stream (muet par défaut).
- Tests : `tests/test_audio_devices.py`, `test_effects.py`,
  `test_audio_stream_offline.py` (sans device) ;
  `test_audio_box_detection.py` (live, `RUN_AUDIO_TESTS=1`, dont
  l'enregistrement).

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
