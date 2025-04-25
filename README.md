# YouTube Downloader Flask

Une application web Flask permettant de télécharger des vidéos YouTube en différentes qualités, avec support pour l'audio uniquement et les playlists.

## Fonctionnalités

- Téléchargement de vidéos YouTube (audio + vidéo)
- Téléchargement audio uniquement
- Choix de la qualité/résolution
- Support des playlists YouTube
- Interface utilisateur moderne et responsive

## Prérequis

- Python 3.7+
- pip (gestionnaire de paquets Python)

## Installation

1. Clonez ce dépôt :
```bash
git clone <url-du-repo>
cd youtube-downloader-flask
```

2. Créez un environnement virtuel et activez-le :
```bash
python -m venv venv
# Sur Windows
venv\Scripts\activate
# Sur Unix ou MacOS
source venv/bin/activate
```

3. Installez les dépendances :
```bash
pip install -r requirements.txt
```

## Utilisation

1. Démarrez l'application :
```bash
python app.py
```

2. Ouvrez votre navigateur et accédez à `http://localhost:5000`

3. Collez l'URL YouTube de votre choix et sélectionnez les options de téléchargement

## Structure du projet

```
youtube-downloader-flask/
├── app.py              # Application Flask principale
├── requirements.txt    # Dépendances Python
├── README.md          # Documentation
└── templates/         # Templates HTML
    └── index.html     # Interface utilisateur
```

## Dépendances principales

- Flask : Framework web
- pytube : Bibliothèque pour le téléchargement YouTube
- flask-wtf : Extension Flask pour les formulaires
- python-dotenv : Gestion des variables d'environnement

## Contribution

Les contributions sont les bienvenues ! N'hésitez pas à ouvrir une issue ou à soumettre une pull request.

## Licence

Ce projet est sous licence MIT. 