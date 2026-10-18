# SmartHome — maison connectée virtuelle avec ntfy

Projet pédagogique de **Bac Pro CIEL** : une maison connectée virtuelle pilotable depuis un navigateur, avec plan interactif, simulation d’équipements et notifications via **ntfy**, sans clé VAPID.

## Architecture

```text
Navigateur PC / téléphone
  ├── HTML5 + CSS3 + JavaScript
  ├── Plan interactif et API Flask
  └── Bouton d’ouverture du topic ntfy
             │ HTTPS en production
             ▼
Flask + Gunicorn sur Render
  ├── État serveur et historique SQLite
  ├── API de simulation d’incidents
  └── POST HTTPS vers ntfy.sh ou un serveur ntfy privé
             ▼
Application ntfy sur le téléphone
  └── Notification système, même si SmartHome est fermé
```

Flask est la source de vérité pour l’état de la maison. ntfy est le service de notification : l’application ntfy du téléphone s’abonne à un topic et le serveur SmartHome publie les alertes sur ce topic.

## Fonctionnalités

- Plan de maison vu du dessus avec entrée, salon, cuisine, chambre, salle de bain et garage.
- Éclairage, intensité, volets, chauffage et température simulée.
- Modes Maison, Nuit et Absence.
- Incidents intrusion, fumée/incendie, fuite d’eau et température basse.
- Acquittement, historique et bouton de notification de test.
- Notifications ntfy depuis le PC vers plusieurs téléphones.
- Aucun certificat VAPID ni souscription Web Push nécessaire.

## Installation locale

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# macOS / Linux
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Créer les variables d’environnement :

```powershell
$env:NTFY_SERVER="https://ntfy.sh"
$env:NTFY_TOPIC="smarthome-ciel-choisir-un-nom-unique"
# Facultatif en développement, obligatoire sur Render
$env:NTFY_TOKEN="tk_..."
$env:FLASK_SECRET_KEY="une-longue-valeur-secrete"
python app.py
```

Ouvrir `http://127.0.0.1:5000`.

## Configuration de ntfy sur téléphone

1. Installer l’application ntfy depuis le magasin du téléphone ou ouvrir `https://ntfy.sh`.
2. Choisir un topic difficile à deviner, par exemple `smarthome-ciel-lycee-48291`.
3. S’abonner à ce topic dans l’application ntfy sur chaque téléphone.
4. Configurer le même nom dans `NTFY_TOPIC` côté serveur.
5. Dans SmartHome, utiliser **Tester une notification ntfy**.
6. Simuler une intrusion depuis le PC.

Le bouton **Ouvrir ntfy** ouvre directement le topic configuré. Le site SmartHome peut être fermé sur le téléphone : c’est l’application ntfy qui reçoit la notification système.

### Choix retenu : topic protégé par token

J’ai choisi un **topic ntfy protégé par token** plutôt qu’un simple topic public. C’est adapté à SmartHome : le téléphone s’abonne au topic dans ntfy, mais seul le serveur Render possédant le token peut publier des alertes.

1. Créez un nom de topic long et difficile à deviner.
2. Dans votre compte ntfy, créez un token avec un droit **Write** uniquement sur ce topic.
3. Ajoutez le token dans Render sous `NTFY_TOKEN`.
4. Ne mettez jamais le token dans GitHub, le JavaScript, une capture ou le README.

Le token n’est jamais envoyé au navigateur : Flask l’utilise seulement dans l’en-tête HTTP vers ntfy.


Variables :

- `NTFY_SERVER` : `https://ntfy.sh` ou l’URL de votre serveur ntfy.
- `NTFY_TOPIC` : nom unique du topic, sans slash.
- `NTFY_TOKEN` : token secret ntfy obligatoire en production pour publier sur le topic protégé.
- `NTFY_TIMEOUT` : délai HTTP en secondes, 10 par défaut.
- `FLASK_SECRET_KEY` : secret Flask.
- `DATABASE_PATH` : chemin de SQLite, `/var/data/smarthome.db` sur Render avec disque.

Les erreurs HTTP ntfy et les erreurs réseau sont visibles dans l’interface et les logs. Le serveur ne prétend pas avoir envoyé une notification quand ntfy répond en erreur.

## Déploiement GitHub + Render

Le site ne peut pas être lancé directement comme application dynamique par GitHub Pages : GitHub héberge des fichiers statiques, alors que SmartHome nécessite Flask et une API serveur. Le dépôt GitHub sert de source, puis Render lance Flask.

1. Créer un dépôt GitHub.
2. Copier les fichiers du projet dans le dépôt.
3. Vérifier que `.env`, les bases locales et les secrets ne sont pas commités.
4. Pousser les fichiers :

```bash
git init
git add .
git commit -m "Créer SmartHome avec ntfy"
git branch -M main
git remote add origin https://github.com/VOTRE_COMPTE/VOTRE_DEPOT.git
git push -u origin main
```

5. Dans Render, choisir **New > Blueprint**.
6. Connecter le dépôt GitHub.
7. Render détecte `render.yaml`, installe `requirements.txt` et lance `gunicorn app:app`.
8. Dans les variables Render, renseigner :

```text
NTFY_SERVER=https://ntfy.sh
NTFY_TOPIC=smarthome-ciel-7f4c9a2e8d1b6f3a5c9e
NTFY_TOKEN=token-ntfy-obligatoire-sur-render
FLASK_SECRET_KEY=secret-long
DATABASE_PATH=/var/data/smarthome.db
```

9. Activer le disque persistant défini dans `render.yaml`.
10. Ouvrir l’URL HTTPS Render.
11. S’abonner au topic depuis le téléphone et tester l’envoi.

Render fournit HTTPS, ce qui permet l’accès mobile sécurisé. Le site peut aussi être déployé sur un autre hébergeur Python qui accepte Gunicorn et les variables d’environnement.

## Tests

```bash
python -m pytest -q
```

Les tests vérifient le tableau de bord, les commandes, les modes, la simulation d’incident, l’appel ntfy, l’absence de topic et les erreurs réseau.

## Démonstration orale de 3 à 5 minutes

1. Présenter le plan et les six pièces.
2. Cliquer sur le salon, allumer l’éclairage et fermer les volets.
3. Activer le mode Absence et montrer la fermeture automatique et l’alarme.
4. Sur le téléphone, ouvrir ntfy avec le bouton SmartHome et s’abonner au topic.
5. Depuis le PC, cliquer sur le test ntfy et montrer la notification système.
6. Fermer ntfy ou verrouiller le téléphone, puis simuler une intrusion.
7. Montrer l’alerte dans SmartHome, l’historique et la notification ntfy.
8. Expliquer que Flask publie une requête HTTPS vers ntfy et que l’application ntfy fonctionne indépendamment du site.

## Limites

La notification dépend de la connexion réseau, des autorisations ntfy, du fonctionnement du système mobile et de ses restrictions d’économie d’énergie. La réception n’est pas garantie dans toutes les conditions. ntfy n’est pas Web Push VAPID : il s’agit d’un service intermédiaire de notification avec abonnement par topic.

Pour une installation réelle, conserver le token ntfy, ajouter une authentification, PostgreSQL, des sauvegardes, HTTPS partout et une gestion fine des droits.
