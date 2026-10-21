"""Configuration d'un envoi quotidien automatique, géré par un worker séparé."""
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, EmailStr, Field
from psycopg2.extras import RealDictCursor
from api.database import get_connection

router = APIRouter(prefix='/profiles', tags=['Automatic email'])

class ScheduleSettings(BaseModel):
    email: EmailStr
    enabled: bool = True
    send_hour: int = Field(default=9, ge=0, le=23)
    send_minute: int = Field(default=0, ge=0, le=59)
    timezone: str = 'Africa/Casablanca'
    max_jobs: int = Field(default=5, ge=1, le=20)
    min_score: float = Field(default=0, ge=0, le=100)

@router.get('/{profile_id}/email-schedule')
def get_schedule(profile_id: int):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute('SELECT id FROM profiles WHERE id=%s', (profile_id,))
            if cur.fetchone() is None:
                raise HTTPException(404, 'Profil introuvable')
            cur.execute('SELECT * FROM email_schedules WHERE profile_id=%s', (profile_id,))
            result = cur.fetchone()
    return {'schedule': dict(result) if result else None}

@router.put('/{profile_id}/email-schedule')
def update_schedule(profile_id: int, data: ScheduleSettings):
    try:
        ZoneInfo(data.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(422, 'Fuseau horaire inconnu')
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM profiles WHERE id=%s', (profile_id,))
            if cur.fetchone() is None:
                raise HTTPException(404, 'Profil introuvable')
            cur.execute('''
                INSERT INTO email_schedules
                (profile_id,recipient_email,enabled,send_hour,send_minute,timezone,max_jobs,min_score)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (profile_id) DO UPDATE SET
                    recipient_email=EXCLUDED.recipient_email,
                    enabled=EXCLUDED.enabled,
                    send_hour=EXCLUDED.send_hour,
                    send_minute=EXCLUDED.send_minute,
                    timezone=EXCLUDED.timezone,
                    max_jobs=EXCLUDED.max_jobs,
                    min_score=EXCLUDED.min_score,
                    updated_at=NOW()
            ''', (profile_id,str(data.email).lower(),data.enabled,data.send_hour,
                  data.send_minute,data.timezone,data.max_jobs,data.min_score))
    return {'status': 'saved', 'profile_id': profile_id, 'enabled': data.enabled}
