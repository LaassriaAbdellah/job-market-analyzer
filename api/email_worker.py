"""Worker quotidien indépendant : python -m api.email_worker

N'envoie que les nouvelles offres déjà présentes dans job_matches.
Le worker doit rester démarré, comme FastAPI.
"""
import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from psycopg2.extras import RealDictCursor
from api.database import get_connection
from api.email_notifications import SendRecommendations, send_recommendations

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger(__name__)


def run_due_schedules():
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT * FROM email_schedules WHERE enabled = TRUE')
            schedules = cur.fetchall()

    for schedule in schedules:
        pid = schedule['profile_id']
        try:
            local_now = datetime.now(ZoneInfo(schedule['timezone']))
            due = (local_now.hour, local_now.minute) >= (
                schedule['send_hour'], schedule['send_minute'])
            if not due:
                continue
            # Réservation atomique : un seul worker prend ce profil pour ce jour.
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        UPDATE email_schedules
                        SET last_attempt_date=%s, last_status='running', last_error=NULL
                        WHERE profile_id=%s AND enabled=TRUE
                          AND (last_attempt_date IS NULL OR last_attempt_date < %s)
                        RETURNING profile_id
                    ''', (local_now.date(), pid, local_now.date()))
                    reserved = cur.fetchone() is not None
            if not reserved:
                continue
            try:
                result = send_recommendations(pid, SendRecommendations(
                    email=schedule['recipient_email'],
                    limit=schedule['max_jobs'],
                    min_score=schedule['min_score'],
                ))
                status = result['status']
                error = None
                log.info('Profil %s : %s, %s offres', pid, status, result.get('sent_jobs', 0))
            except Exception as exc:
                status = 'failed'
                error = str(exc)[:500]
                log.exception('Envoi échoué pour profil %s', pid)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute('''
                        UPDATE email_schedules SET last_status=%s, last_error=%s
                        WHERE profile_id=%s
                    ''', (status, error, pid))
        except Exception:
            log.exception('Erreur de planification pour profil %s', pid)


if __name__ == '__main__':
    log.info('Worker e-mail automatique démarré')
    while True:
        try:
            run_due_schedules()
        except Exception:
            log.exception('Erreur de cycle du worker')
        time.sleep(60)
