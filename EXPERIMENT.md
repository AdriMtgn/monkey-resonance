# Expérience — Pedalboard (Spotify) à la place de pyo

Branche `exp/spotify-pedalboard`, basée sur `main` @ `c19c2c8`.

## Objectif

Évaluer si **Pedalboard** peut remplacer `pyo` pour la chaîne d'effets temps
réel de Monkey Resonance, avec une meilleure maintenabilité et sans dégrader la
latence.

## Mise au point sur le nom

Spotify ne publie pas de « DAW framework » Python. Le projet visé est
**Pedalboard** (GPLv3, basé sur JUCE) : I/O audio, effets, hébergement de
plugins VST3/AU. Ce n'est **pas** un DAW : pas de séquenceur, pas de transport,
pas de synthèse ni d'objets générateurs comme pyo.

## Vérifié le 2026-10-31 (hôte, hors container)

- `pedalboard 0.9.26` s'installe depuis PyPI (wheel Linux x86_64) et traite un
  buffer stéréo 48 kHz hors-ligne : `Gain → Delay → Reverb` OK.
- `AudioStream` expose `input_device_names` / `output_device_names` et voit
  l'AudioBox USB 96 (ALSA/PipeWire) sur l'hôte.
- `AudioStream` est supporté sur Linux depuis 0.9.14 ; `read()` permet de
  capturer l'entrée, `plugins` traite l'audio entrant → sortant.
- Ouverture live sur l'hôte : `ValueError: no channels`. L'AudioBox est
  occupée (`aplay -l` : subdevice 0/1) par le container principal qui tourne
  depuis 2 jours. À retester après l'avoir arrêté.
- **Non testé** : streaming temps réel (pas de test live pour éviter de sortir
  du son sur les enceintes et de provoquer un larsen). À faire sur l'AudioBox
  avec un niveau de sortie bas.

## Correspondance pyo → Pedalboard

| pyo | Pedalboard |
| --- | --- |
| `pyo.Input(i)` | `AudioStream(input_device_name=..., output_device_name=...)` |
| `pyo.Chorus`, `Delay`, `Reverb`… | `Chorus`, `Delay`, `Reverb`… |
| `CustomDelay(pyo.PyoObject)` | `Delay` natif, ou plugin VST3 |
| `pyo.Record(output)` | `AudioStream.read()` (capte l'entrée, **pas** la sortie post-effets) |
| Chaîne `PyoObject` / `setInput` | `Pedalboard([...])` mutable (`append`, `del`, paramètres) |
| Serveur pyo + `s.boot()` | pas d'équivalent : le stream gère le device |

## Écarts et risques

1. **Pas de synthèse** : si l'app doit générer des sons (et pas seulement
   traiter l'entrée), pyo reste nécessaire. Aujourd'hui `main.py` ne crée que
   des `Input`, donc le périmètre est compatible.
2. **Enregistrement post-effets** : `read()` capture l'entrée. Pour
   `start_recording()` (qui enregistre `self.output` chez pyo), il faudra un
   tap dans la chaîne (sous-classe de `Plugin` ou capture côté callback), à
   valider.
3. **Latence** : `AudioStream.buffer_size` est réglable, mais il n'y a pas de
   garantie temps réel dure (JUCE + thread interne). Mesurer le round-trip sur
   l'AudioBox. Ordre de grandeur : 256 frames @ 48 kHz ≈ 5,3 ms de buffer.
4. **Licence GPLv3** : le repo n'a pas de LICENSE. Si une diffusion non-GPL
   est prévue, c'est bloquant.
5. **Contrat `sys.modules["__main__"]`** : `app/main.py` doit continuer à
   exposer `AudioStream`, `audio_devices` et `inputs`. Un adaptateur
   `PedalboardStream` doit garder l'API (`add_effect`, `remove_effect`,
   `start`, `stop`, `save_effects`, `load_effects`, `start_recording`,
   `stop_recording`, `global_volume`).
6. **Thread-safety** : conserver la règle projet — un seul thread de contrôle
   pour l'audio. Pedalboard libère le GIL pendant le processing, mais la chaîne
   ne doit pas être mutée depuis FastAPI/MCP.
7. **Formats sauvegardés** : `saved_effects/*.json` stocke `module.Class` pyo +
   kwargs. Prévoir un mapping vers les classes Pedalboard (ou un champ
   `engine`).

## Spike proposé

1. `uv venv .venv && uv pip install pedalboard` dans ce worktree.
2. Script `scripts/spike_pedalboard.py` :
   - hors-ligne : sine → chaîne → WAV (déjà validé) ;
   - live : `AudioStream` sur l'AudioBox, 5 s, mesure de la latence perçue et
     de `dropped_input_frame_count`.
3. Adaptateur `PedalboardStream` avec l'API de `AudioStream` et tests unitaires
   sans device (add/remove/save/load).
4. Brancher `main.py` derrière un flag (`--engine pedalboard|pyo`) pour
   comparer sans casser l'existant.
5. Décider : remplacement complet, ou pyo pour la synthèse + Pedalboard pour
   les effets.

## Lancer ce worktree en parallèle

Le compose de cette branche monte `.:/code` (plus de chemin absolu vers le repo
principal) et lit `MKR_PORT` :

```bash
# API sur http://localhost:8011/docs
MKR_PORT=8011 docker compose run --rm --service-ports mkr \
  python main.py --with_api
```

`pwd` doit être la racine de ce worktree : le conteneur exécute alors bien le
code de la branche. L'autre worktree utilise `8012`, le repo principal garde
`8005`.
