# USAGE MCP — Guide rapide pour l'ingé son

Contexte
- Ce MCP est destiné à être utilisé par un ingénieur son virtuel qui assiste ses musiciens en temps réel.
- Il connaît la librairie pyo et utilise les objets `AudioStream` (dans `app/libs/audio_stream.py`) pour gérer les pistes.
- Le MCP expose des outils (tools) RPC via `mcp.tool()` ; on peut appeler `list_globals()` et `call_method_on_global()` par défaut.

Principes d'utilisation
- Le MCP manipule directement les objets du module `__main__` (exposés via les tools). Les objets intéressants : `s` (serveur pyo), `inputs` (liste d'`AudioStream`).
- Préfère appeler les méthodes via `call_method_on_global()` ou, si disponible, des tools dédiés (p.ex. `list_inputs()` si ajouté).
- Attention au thread-safety : pour les opérations qui touchent Pyo, privilégier l'exécution dans le main thread (ou utiliser un mécanisme `call_in_main()` / queue si nécessaire).

Commandes et exemples (pattern ingénieur son)
- Objectif: répondre aux demandes des musiciens (activer/désactiver effets, ajuster paramètres, sauvegarder presets).

1) Lister les pistes disponibles
- But: voir quelles pistes `AudioStream` sont présentes
- Appel:
  - `list_globals()` -> chercher `"inputs"` dans la liste
  - `call_method_on_global("inputs", "__len__")` -> nombre de pistes
  - Boucle pour lister les objets:
    - `call_method_on_global("inputs", "__getitem__", args=[0])` -> représentation de la piste 0

2) Ajouter un effet (ex: chorus) sur la piste 0
- But: appliquer un effet Pyo compatible à la chaîne d'effets de l'`AudioStream`
- Exemple (appel RPC):
  - `call_method_on_global("inputs", "__getitem__", args=[0])` -> récupère l'objet (représentation)
  - Pour exécuter la méthode `add_effect`, on peut appeler directement via le nom de l'objet global si tu as enregistré les instances sous un nom; sinon, utilise une helper côté main pour exécuter `inputs[0].add_effect(...)`.
- Invocation type (si la méthode est exposée via `call_method_on_global` en ciblant `inputs`):
  - `call_method_on_global("inputs", "__getitem__", args=[0])` puis `call_method_on_global("inputs", "add_effect", args=[0, "pyo.Delay", {"delay":0.25, "feedback":0.3}])`
  - Remarque: `add_effect` attend une classe pyo, pas une string — il faut passer un objet effect. Si on ne peut pas transmettre des classes via RPC, crée un helper côté `main` qui accepte le nom de la classe et l'instancie.

3) Retirer un effet (index)
- Appel:
  - `call_method_on_global("inputs", "remove_effect", args=[index])` -> retire l'effet à `index`

4) Sauvegarder / charger une chaîne d'effets
- Sauvegarder:
  - `call_method_on_global("inputs", "__getitem__", args=[0])` puis `call_method_on_global("inputs", "save_effects", args=["preset_name"])`
- Charger:
  - `call_method_on_global("inputs", "load_effects", args=["preset_name"])`

5) Démarrer / arrêter la sortie d'une piste
- `call_method_on_global("inputs", "start")`
- `call_method_on_global("inputs", "stop")`

Exemples réels — dialogues musiciens / ingénieur
- Musicien: "Je veux plus d'espace sur ma voix." → Ingé (MCP):
  - `call_method_on_global("inputs", "add_effect", args=[None, "pyo.Freeverb", {"size":0.9, "damp":0.5}])`
- Musicien: "Enlève le delay sur la guitare" → Ingé (MCP):
  - Identifier la piste (ex: inputs[2]) puis `call_method_on_global("inputs", "remove_effect", args=[i_delay])`
- Musicien: "Sauvegarde ce patch" → Ingé (MCP):
  - `call_method_on_global("inputs", "save_effects", args=["live_patch_1"])`

Notes techniques et recommandations
- `AudioStream.add_effect` prend une classe pyo (p.ex. `pyo.Delay`, `pyo.Chorus`) et un dictionnaire de paramètres. Si tu passes le nom en string via le MCP, implémenter côté main une petite fabrique qui importe et instancie la classe par son nom (utilise `importlib.import_module`).
- Pour éviter les problèmes liés au thread, implémente `call_in_main()` (pattern queue) : le MCP poste la commande et le main l'exécute dans son thread pyo. Cela évite les plantages liés aux appels audio depuis un thread secondaire.
- Limiter l'exposition: si tu ne veux pas exposer tout `globals()`, crée un dict filtré `{ 's': s, 'inputs': inputs }` et expose seulement cela via le MCP.

Prochaines étapes possibles
- Ajouter un tool `list_inputs()` pour renvoyer directement les pistes et leurs états.
- Ajouter un helper `apply_effect_by_name(track_index, effect_name, params)` côté main pour simplifier les appels RPC.

Fin — premier jet concis. On enrichira avec des snippets plus détaillés et des outils helper côté MCP si tu veux.
