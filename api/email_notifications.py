"""Envoi manuel des recommandations par Gmail SMTP."""
import os
import smtplib
import ssl
from email.message import EmailMessage
from html import escape

from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field
from psycopg2.extras import RealDictCursor

from api.database import get_connection

load_dotenv()
router = APIRouter(prefix='/profiles', tags=['Email notifications'])


class SendRecommendations(BaseModel):
    email: EmailStr
    limit: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0, ge=0, le=100)


@router.post('/{profile_id}/send-recommendations')
def send_recommendations(profile_id: int, data: SendRecommendations):
    smtp_user = os.getenv('SMTP_USER', '').strip()
    smtp_password = os.getenv('SMTP_PASSWORD', '').replace(' ', '')
    smtp_host = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    if not smtp_user or not smtp_password:
        raise HTTPException(503, 'Configurer SMTP_USER et SMTP_PASSWORD dans .env')

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id, name FROM profiles WHERE id = %s', (profile_id,))
            profile = cur.fetchone()
            if profile is None:
                raise HTTPException(404, 'Profil introuvable')
            # N'envoyer que les offres non déjà envoyées à ce destinataire.
            cur.execute('''
                SELECT j.id, j.title, j.company, j.location, j.url,
                       COALESCE(m.adjusted_score, m.final_score) AS score
                FROM job_matches m
                JOIN jobs j ON j.id = m.job_id
                WHERE m.profile_id = %s
                  AND COALESCE(m.adjusted_score, m.final_score) >= %s
                  AND NOT EXISTS (
                      SELECT 1 FROM email_sent_jobs s
                      WHERE s.profile_id = m.profile_id
                        AND s.job_id = m.job_id
                        AND LOWER(s.recipient_email) = LOWER(%s)
                  )
                ORDER BY COALESCE(m.adjusted_score, m.final_score) DESC, j.id
                LIMIT %s
            ''', (profile_id, data.min_score, str(data.email), data.limit))
            jobs = cur.fetchall()

    if not jobs:
        return {'status': 'no_new_jobs', 'sent_jobs': 0,
                'message': 'Aucune nouvelle offre à envoyer avec ces critères.'}

    message = EmailMessage()
    message['Subject'] = f'Job Market Analyzer - {len(jobs)} nouvelles recommandations'
    message['From'] = smtp_user
    message['To'] = str(data.email)
    lines = [f"Bonjour {profile['name']},", '', 'Voici vos recommandations :', '']
    html_items = []
    for job in jobs:
        title = job['title'] or 'Offre sans titre'
        company = job['company'] or 'Entreprise non précisée'
        location = job['location'] or 'Localisation non précisée'
        score = float(job['score'])
        url = job['url']
        lines += [f'{title} - {company}', f'Localisation : {location}',
                  f'Score ajusté : {score:.1f} %', f'Lien : {url}', '']
        html_items.append(
            f'<li><strong>{escape(title)}</strong> - {escape(company)}<br>'
            f'{escape(location)} | Score : {score:.1f} %<br>'
            f'<a href="{escape(url, quote=True)}">Voir l\'offre</a></li>'
        )
    lines.append('Bonne chance dans vos candidatures !')
    message.set_content('\n'.join(lines))
    message.add_alternative(
        f'<html><body><p>Bonjour {escape(profile["name"])},</p>'
        f'<p>Voici vos recommandations :</p><ul>{"".join(html_items)}</ul>'
        '<p>Bonne chance dans vos candidatures !</p></body></html>',
        subtype='html'
    )

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.ehlo()
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
            server.login(smtp_user, smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as exc:
        # Pas de journalisation du mot de passe ni de détails d'authentification.
        raise HTTPException(502, 'Envoi Gmail impossible. Vérifiez SMTP et le mot de passe d’application.') from exc

    # L'historique n'est écrit qu'après l'envoi SMTP réussi.
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('''
                INSERT INTO email_notifications(profile_id, recipient_email, jobs_count, status)
                VALUES (%s, %s, %s, 'sent')
            ''', (profile_id, str(data.email), len(jobs)))
            for job in jobs:
                cur.execute('''
                    INSERT INTO email_sent_jobs(profile_id, recipient_email, job_id)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (profile_id, recipient_email, job_id) DO NOTHING
                ''', (profile_id, str(data.email).lower(), job['id']))
    return {'status': 'sent', 'sent_jobs': len(jobs), 'recipient': str(data.email)}
