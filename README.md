# Job Market Analyzer

Application d'analyse d'offres avec collecte depuis Remotive, Jobicy et Free-Work, stockage PostgreSQL, extraction de compétences, analyse de CV et matching par profil.

## Pipeline de collecte

Le service `pipeline` de Docker Compose lance une collecte à son démarrage, puis toutes les six heures. Il exécute les étapes suivantes :

1. collecte Remotive, Jobicy et Free-Work avec retries HTTP sur les erreurs temporaires ;
2. déduplication et sauvegarde du dernier lot brut dans `data/raw/latest_jobs.json` ;
3. normalisation dans `data/processed/normalized_jobs.json` ;
4. UPSERT des offres dans PostgreSQL avec la clé `(source, external_id)` ;
5. analyse des descriptions depuis PostgreSQL et enregistrement dans `job_analysis` ;
6. persistance des compteurs de cette exécution dans `pipeline_runs`.

Jobicy utilise sa pagination par curseur. Remotive renvoie les résultats correspondant au filtre dans une seule réponse et fournit un compte de vérification. Free-Work est paginé jusqu'au nombre de résultats déclaré ou à la limite configurée.

Le worker détient un verrou PostgreSQL pendant toute l'exécution afin d'éviter deux pipelines simultanés. Une erreur sur une source est journalisée ; les sources disponibles peuvent poursuivre le cycle, qui sera marqué `partial`. Si aucune source ne fonctionne ou si le volume total est inférieur au seuil, le chargement est annulé et l'exécution passe en échec.

### Configuration

Créer un fichier `.env` local (ne pas le committer) avec au minimum :

```dotenv
POSTGRES_DB=job_market
POSTGRES_USER=job_user
POSTGRES_PASSWORD=un_mot_de_passe_fort
```

Options du pipeline :

```dotenv
PIPELINE_INTERVAL_HOURS=6
PIPELINE_RUN_ON_START=true
PIPELINE_MIN_JOBS=1
HTTP_RETRIES=3
HTTP_RETRY_BACKOFF=1
JOBICY_PAGE_SIZE=100
JOBICY_MAX_PAGES_PER_FILTER=10
FREEWORK_MAX_PAGES_PER_KEYWORD=10
```

Démarrer les services :

```bash
docker compose up -d --build
```

Lancer un cycle ponctuel :

```bash
docker compose run --rm pipeline python -m scripts.pipeline --once
```

Consulter les dernières exécutions : `GET http://localhost:8000/operations/pipeline/runs`. Les journaux détaillés sont accessibles avec `docker compose logs -f pipeline`.

## Lancer localement

Créer un environnement virtuel, installer `requirements.txt`, démarrer PostgreSQL et définir ses variables de connexion dans `.env`. Puis lancer un cycle ponctuel :

```bash
python -m scripts.pipeline --once
```

Lancer uniquement les collecteurs et la normalisation reste possible avec les scripts `scripts/scraper.py`, `scripts/web_scraper.py` et `scripts/normalizer.py`. Le worker planifié s'exécute dans Docker Compose.

## API et interface

- API FastAPI : `http://localhost:8000` (documentation OpenAPI sous `/docs`).
- Interface Streamlit : `http://localhost:8501`.
- L'API accepte l'analyse de CV PDF/DOCX et le matching à la demande pour un profil.

## Données et opérations

- `data/raw/latest_jobs.json` : lot brut de la dernière exécution.
- `data/processed/normalized_jobs.json` : lot normalisé correspondant.
- `jobs` : offres courantes, identifiées par `(source, external_id)`.
- `job_analysis` : compétences extraites et description nettoyée.
- `pipeline_runs` : statut et compteurs d'exécution, source par source.

La migration de `jobs.external_id` remplit cette colonne depuis les IDs historiques, puis ajoute une contrainte d'unicité sur `(source, external_id)`. Si la base existante contient déjà plusieurs annonces pour la même paire, la migration échoue volontairement afin qu'elles soient examinées au lieu d'en supprimer silencieusement.
