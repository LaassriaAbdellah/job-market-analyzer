# Job Market Analyzer

Prototype Python qui collecte des offres d'emploi IT depuis les API Remotive et Jobicy, ainsi que les pages Free-Work, puis extrait des compétences et calcule un score de correspondance avec `config/my_profile.json`.

## Structure

- `scripts/scraper.py` : collecte Remotive et Jobicy.
- `scripts/web_scraper.py` : collecte Free-Work.
- `scripts/parser.py` : nettoyage des descriptions et extraction des compétences.
- `scripts/common.py` : chemins du projet, identifiants déterministes et déduplication.
- `config/` : dictionnaire de compétences et profil candidat.
- `data/` : fichiers JSON locaux générés (ignorés par Git).

## Installation

Depuis la racine du projet, crée et active un environnement virtuel :

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Sous macOS/Linux, active-le avec `source .venv/bin/activate`. Installe ensuite les dépendances :

```bash
python -m pip install -r requirements.txt
```

Le parseur utilise spaCy. Pour activer l'extraction NLP, installe les modèles anglais et français :

```bash
python -m spacy download en_core_web_sm
python -m spacy download fr_core_news_sm
```

Sans ces modèles, l'extraction par dictionnaire fonctionne, mais l'extraction NLP est désactivée et un avertissement est journalisé.

## Exécution

Depuis la racine du projet :

```bash
python scripts/scraper.py
python scripts/web_scraper.py
python scripts/parser.py
```

Le premier collecteur ajoute les offres aux données locales existantes. Le collecteur Free-Work les fusionne également et déduplique par ID stable et URL. Le parseur lit `data/raw_jobs.json` et écrit `data/parsed_jobs.json`. Les chemins sont résolus depuis l'emplacement du projet, pas depuis le répertoire courant.

Les fichiers JSON produits dans `data/` sont des données locales et ne sont pas suivis par Git.

## Suite envisagée

Une base PostgreSQL, une API, une interface et des méthodes de recherche sémantique sont des pistes futures ; elles ne sont pas implémentées dans l'état actuel.
