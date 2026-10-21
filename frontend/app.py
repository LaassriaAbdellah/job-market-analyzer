import os
from urllib.parse import quote

import requests
import streamlit as st
from frontend.dashboard import render_dashboard

API_URL = os.getenv('API_URL', 'http://127.0.0.1:8000').rstrip('/')
st.set_page_config(page_title='Job Market Analyzer', page_icon='🎯', layout='wide')


def api_request(method, endpoint, **kwargs):
    """Appelle FastAPI et affiche les erreurs utiles."""
    try:
        response = requests.request(method, f'{API_URL}{endpoint}', timeout=300, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.HTTPError as exc:
        detail = None
        if exc.response is not None:
            try:
                detail = exc.response.json().get('detail')
            except ValueError:
                pass
        st.error(f'Erreur API : {detail or str(exc)}')
    except requests.exceptions.RequestException as exc:
        st.error(f'Connexion à FastAPI impossible : {exc}')
    return None


def parse_list(text):
    """Convertit une chaîne séparée par des virgules en liste sans doublons."""
    result, seen = [], set()
    for item in text.split(','):
        item = item.strip()
        if item and item.casefold() not in seen:
            result.append(item)
            seen.add(item.casefold())
    return result


EXPERIENCE_OPTIONS = {
    'Tous les niveaux': 'any',
    'Stage / PFE': 'intern',
    'Junior / Débutant': 'junior',
    'Intermédiaire': 'mid',
    'Senior': 'senior',
}
CONTRACT_OPTIONS = {
    'Tous les contrats': 'any',
    'Stage': 'internship',
    'CDI / Temps plein': 'full_time',
    'Temps partiel': 'part_time',
    'Contrat / Freelance': 'contract',
}


def label_for_value(options, value):
    return next((label for label, code in options.items() if code == value), next(iter(options)))


def set_form_fields(profile):
    """Préremplit le formulaire d'édition avant la création des widgets."""
    st.session_state['edit_name'] = profile.get('name') or ''
    st.session_state['edit_skills'] = ', '.join(profile.get('skills') or [])
    st.session_state['edit_roles'] = ', '.join(profile.get('target_roles') or [])
    st.session_state['edit_experience'] = label_for_value(
        EXPERIENCE_OPTIONS, profile.get('experience_level')
    )
    st.session_state['edit_contract'] = label_for_value(
        CONTRACT_OPTIONS, profile.get('contract_type')
    )
    st.session_state['edit_location'] = profile.get('preferred_location') or ''


st.title('🎯 Job Market Analyzer')
st.write(
    "Plateforme intelligente de recommandation d'offres d'emploi "
    'basée sur le NLP et le Machine Learning.'
)
st.divider()

tab_profile, tab_matching, tab_results, tab_favorites, tab_email, tab_analytics = st.tabs(
    [
        '👤 Mon profil',
        '🧠 Matching intelligent',
        '📊 Mes recommandations',
        '🔖 Mes favoris',
        '📧 Notifications',
        '📈 Analytics'
    ]
)

with tab_profile:
    st.subheader('Importer et analyser mon CV')
    st.write('Importe ton CV pour détecter automatiquement tes compétences techniques.')
    uploaded_cv = st.file_uploader(
        'Choisir un CV (PDF ou DOCX)', type=['pdf', 'docx'], key='cv_uploader'
    )
    if uploaded_cv is not None:
        st.info(f'Fichier sélectionné : {uploaded_cv.name}')
        if st.button('Analyser mon CV', type='primary'):
            with st.spinner('Analyse du CV en cours...'):
                result = api_request(
                    'POST', '/cv/analyze',
                    files={'file': (
                        uploaded_cv.name, uploaded_cv.getvalue(),
                        uploaded_cv.type or 'application/octet-stream'
                    )},
                )
            if result is not None:
                skills = result.get('skills', [])
                st.session_state['cv_skills'] = skills
                st.session_state['skills_input'] = ', '.join(skills)
                st.session_state['edit_skills'] = ', '.join(skills)
                st.success(f'{len(skills)} compétences détectées !')

    if st.session_state.get('cv_skills'):
        st.write('**Compétences extraites du CV :**')
        st.write(', '.join(st.session_state['cv_skills']))
        st.caption('Tu peux corriger ces compétences avant d’enregistrer ton profil.')

    st.divider()
    st.subheader('Gestion des profils candidats')
    mode = st.radio(
        'Que souhaites-tu faire ?',
        ['Créer un profil', 'Modifier un profil existant'],
        horizontal=True,
    )

    if mode == 'Créer un profil':
        if 'skills_input' not in st.session_state:
            st.session_state['skills_input'] = ''
        with st.form('create_profile_form'):
            name = st.text_input('Nom du candidat', placeholder='Ex : Candidat Data')
            skills_text = st.text_area(
                'Compétences techniques', key='skills_input',
                placeholder='Python, SQL, Pandas, Scikit-learn, PostgreSQL',
            )
            roles_text = st.text_area(
                'Métiers recherchés',
                placeholder='Data Scientist, Data Engineer, Machine Learning Engineer',
            )
            st.subheader('Mes préférences de recherche')
            c1, c2 = st.columns(2)
            with c1:
                experience_label = st.selectbox(
                    "Niveau d'expérience recherché", list(EXPERIENCE_OPTIONS), index=1
                )
            with c2:
                contract_label = st.selectbox(
                    'Type de contrat recherché', list(CONTRACT_OPTIONS), index=1
                )
            location = st.text_input(
                'Localisation préférée', value='Morocco',
                placeholder='Ex : Morocco, Rabat, Casablanca',
            )
            submitted = st.form_submit_button('Créer mon profil', type='primary')

        if submitted:
            skills, roles = parse_list(skills_text), parse_list(roles_text)
            if not name.strip():
                st.warning('Veuillez saisir le nom du candidat.')
            elif not skills:
                st.warning('Veuillez renseigner au moins une compétence.')
            elif not roles:
                st.warning('Veuillez renseigner au moins un métier recherché.')
            else:
                payload = {
                    'name': name.strip(),
                    'skills': skills,
                    'target_roles': roles,
                    'experience_level': EXPERIENCE_OPTIONS[experience_label],
                    'contract_type': CONTRACT_OPTIONS[contract_label],
                    'preferred_location': location.strip(),
                }
                result = api_request('POST', '/profiles', json=payload)
                if result is not None:
                    st.session_state['profile_id'] = int(result['id'])
                    st.success(f"Profil créé avec succès ! Identifiant : {result['id']}")
                    st.info('Tu peux maintenant lancer le matching avec ce profil.')

    else:
        profiles_result = api_request('GET', '/profiles')
        profiles = profiles_result.get('profiles', []) if profiles_result else []
        if not profiles:
            st.info('Aucun profil disponible. Crée d’abord un profil.')
        else:
            profiles_by_id = {int(p['id']): p for p in profiles}
            profile_ids = list(profiles_by_id)
            current_id = int(st.session_state.get('profile_id', profile_ids[0]))
            if st.session_state.get('edit_selected_id') not in profiles_by_id:
                st.session_state['edit_selected_id'] = (
                    current_id if current_id in profiles_by_id else profile_ids[0]
                )

            selected_id = st.selectbox(
                'Sélectionner un profil à modifier',
                profile_ids,
                format_func=lambda pid: f"#{pid} — {profiles_by_id[pid].get('name', '')}",
                key='edit_selected_id',
            )
            if st.session_state.get('edit_loaded_id') != selected_id:
                set_form_fields(profiles_by_id[selected_id])
                st.session_state['edit_loaded_id'] = selected_id

            with st.form('edit_profile_form'):
                name = st.text_input('Nom du candidat', key='edit_name')
                skills_text = st.text_area('Compétences techniques', key='edit_skills')
                roles_text = st.text_area('Métiers recherchés', key='edit_roles')
                st.subheader('Mes préférences de recherche')
                c1, c2 = st.columns(2)
                with c1:
                    experience_label = st.selectbox(
                        "Niveau d'expérience recherché", list(EXPERIENCE_OPTIONS),
                        key='edit_experience',
                    )
                with c2:
                    contract_label = st.selectbox(
                        'Type de contrat recherché', list(CONTRACT_OPTIONS),
                        key='edit_contract',
                    )
                location = st.text_input('Localisation préférée', key='edit_location')
                submitted = st.form_submit_button('Enregistrer les modifications', type='primary')

            if submitted:
                skills, roles = parse_list(skills_text), parse_list(roles_text)
                if not name.strip():
                    st.warning('Veuillez saisir le nom du candidat.')
                elif not skills:
                    st.warning('Veuillez renseigner au moins une compétence.')
                elif not roles:
                    st.warning('Veuillez renseigner au moins un métier recherché.')
                else:
                    payload = {
                        'name': name.strip(),
                        'skills': skills,
                        'target_roles': roles,
                        'experience_level': EXPERIENCE_OPTIONS[experience_label],
                        'contract_type': CONTRACT_OPTIONS[contract_label],
                        'preferred_location': location.strip(),
                    }
                    result = api_request('PUT', f'/profiles/{selected_id}', json=payload)
                    if result is not None:
                        st.session_state['profile_id'] = int(selected_id)
                        st.success(f'Profil #{selected_id} mis à jour avec succès !')
                        st.info('Relance le matching pour recalculer les recommandations avec les nouvelles données.')

with tab_matching:
    st.subheader('Lancer le matching intelligent')
    st.write('Notre algorithme compare ton profil aux offres disponibles en utilisant :')
    c1, c2, c3 = st.columns(3)
    c1.metric('Similarité sémantique', '50 %')
    c2.metric('Compatibilité métier', '30 %')
    c3.metric('Compétences', '20 %')
    st.caption('Le classement final prend également en compte les préférences du candidat.')
    profile_id = st.number_input(
        'Identifiant du profil', min_value=1,
        value=int(st.session_state.get('profile_id', 1)), step=1,
        key='matching_profile_id',
    )
    if st.button('🚀 Lancer le matching', type='primary'):
        with st.spinner('Analyse des offres et calcul des scores...'):
            result = api_request('POST', f'/profiles/{profile_id}/match')
        if result is not None:
            st.session_state['profile_id'] = int(profile_id)
            st.success(f"Matching terminé : {result.get('matched_jobs', 0)} offres analysées.")

with tab_results:
    st.subheader('Mes offres recommandées')
    result_profile_id = st.number_input(
        'Identifiant du profil à consulter', min_value=1,
        value=int(st.session_state.get('profile_id', 1)), step=1,
        key='results_profile_id',
    )
    c1, c2 = st.columns(2)
    with c1:
        min_score = st.slider('Score minimum', min_value=0, max_value=100, value=0)
    with c2:
        limit = st.selectbox("Nombre d'offres", [5, 10, 20, 50], index=1)
    if st.button('Afficher les recommandations'):
        result = api_request(
            'GET', f'/profiles/{result_profile_id}/matches',
            params={'limit': limit, 'min_score': min_score},
        )
        if result is not None:
            st.session_state['last_results'] = result
            st.session_state['last_results_profile_id'] = int(result_profile_id)

    result = (st.session_state.get('last_results')
              if st.session_state.get('last_results_profile_id') == int(result_profile_id)
              else None)
    if result is not None:
        matches = result.get('matches', [])
        st.metric('Offres affichées', len(matches))
        if not matches:
            st.info('Aucune offre ne correspond aux critères sélectionnés.')
        for index, job in enumerate(matches, 1):
            with st.container(border=True):
                st.subheader(f"{index}. {job.get('title') or 'Offre sans titre'}")
                st.write(f"**Entreprise :** {job.get('company') or 'Non précisée'}")
                st.write(f"**Localisation :** {job.get('location') or 'Non précisée'}")
                base_score = float(job.get('final_score') or 0)
                adjusted = job.get('adjusted_score')
                display_score = float(adjusted) if adjusted is not None else base_score
                st.progress(min(max(display_score / 100, 0.0), 1.0))
                st.write(f'**Score ajusté :** {display_score:.2f} %')
                st.caption(f'Score hybride initial : {base_score:.2f} %')
                c1, c2, c3 = st.columns(3)
                c1.metric('Sémantique', f"{float(job.get('semantic_score') or 0):.1f} %")
                c2.metric('Métier', f"{float(job.get('role_score') or 0):.1f} %")
                c3.metric('Compétences', f"{float(job.get('skill_score') or 0):.1f} %")
                if job.get('url'):
                    st.link_button("Voir l'offre", job['url'])
                job_id = str(job['id'])
                if st.button('🔖 Ajouter aux favoris', key=f'fav_add_{result_profile_id}_{job_id}'):
                    saved = api_request(
                        'POST',
                        f'/profiles/{int(result_profile_id)}/favorites/{quote(job_id, safe="")}'
                    )
                    if saved is not None:
                        if saved.get('status') == 'already_saved':
                            st.info('Cette offre est déjà dans tes favoris.')
                        else:
                            st.success('Offre ajoutée aux favoris !')


with tab_favorites:
    st.subheader('🔖 Mes offres favorites')
    favorite_profile_id = st.number_input(
        'Identifiant du profil pour les favoris', min_value=1,
        value=int(st.session_state.get('profile_id', 1)), step=1,
        key='favorite_profile_id',
    )
    if st.button('Actualiser mes favoris'):
        st.session_state.pop('favorites_cache', None)

    if (st.session_state.get('favorites_profile_id') != int(favorite_profile_id)
            or 'favorites_cache' not in st.session_state):
        response = api_request('GET', f'/profiles/{int(favorite_profile_id)}/favorites')
        if response is not None:
            st.session_state['favorites_cache'] = response
            st.session_state['favorites_profile_id'] = int(favorite_profile_id)

    favorites_result = (st.session_state.get('favorites_cache')
                        if st.session_state.get('favorites_profile_id') == int(favorite_profile_id)
                        else None)
    if favorites_result is not None:
        favorites = favorites_result.get('favorites', [])
        st.metric('Offres sauvegardées', len(favorites))
        if not favorites:
            st.info('Tu n’as pas encore ajouté d’offres favorites pour ce profil.')
        for job in favorites:
            job_id = str(job['job_id'])
            with st.container(border=True):
                st.subheader(job.get('title') or 'Offre sans titre')
                st.write(f"**Entreprise :** {job.get('company') or 'Non précisée'}")
                st.write(f"**Localisation :** {job.get('location') or 'Non précisée'}")
                score = job.get('adjusted_score')
                if score is None:
                    score = job.get('final_score')
                if score is not None:
                    st.write(f'**Score :** {float(score):.2f} %')
                if job.get('url'):
                    st.link_button("Voir l'offre", job['url'])
                if st.button('🗑️ Retirer des favoris', key=f'fav_remove_{favorite_profile_id}_{job_id}'):
                    removed = api_request(
                        'DELETE',
                        f'/profiles/{int(favorite_profile_id)}/favorites/{quote(job_id, safe="")}'
                    )
                    if removed is not None:
                        st.session_state.pop('favorites_cache', None)
                        st.rerun()


with tab_email:
    st.subheader('📧 Envoyer mes recommandations par Gmail')
    st.write('Envoie uniquement les nouvelles offres non déjà transmises à cette adresse.')
    with st.form('email_recommendations_form'):
        email_profile_id = st.number_input(
            'Identifiant du profil', min_value=1,
            value=int(st.session_state.get('profile_id', 1)), step=1,
            key='email_profile_id',
        )
        recipient = st.text_input('Adresse e-mail du destinataire',
                                  placeholder='exemple@gmail.com')
        c1, c2 = st.columns(2)
        with c1:
            email_limit = st.selectbox('Nombre maximum d’offres', [3, 5, 10, 20], index=1)
        with c2:
            email_min_score = st.slider('Score minimum pour l’e-mail', 0, 100, 0)
        send_email = st.form_submit_button('📨 Envoyer mes recommandations', type='primary')
    if send_email:
        if not recipient.strip() or '@' not in recipient:
            st.warning('Saisis une adresse e-mail valide.')
        else:
            with st.spinner('Envoi en cours...'):
                response = api_request(
                    'POST', f'/profiles/{int(email_profile_id)}/send-recommendations',
                    json={'email': recipient.strip(), 'limit': email_limit,
                          'min_score': email_min_score},
                )
            if response is not None:
                if response.get('status') == 'sent':
                    st.success(f"{response['sent_jobs']} offre(s) envoyée(s) à {response['recipient']} !")
                else:
                    st.info(response.get('message', 'Aucune nouvelle offre à envoyer.'))


# === Programmation quotidienne automatique ===
with tab_email:
    st.divider()
    st.subheader('⏰ Envoi automatique quotidien')
    st.caption('Le worker envoie uniquement les nouvelles offres, chaque jour à l’heure choisie.')
    auto_pid = st.number_input(
        'Profil pour les envois automatiques', min_value=1,
        value=int(st.session_state.get('profile_id', 1)),
        step=1, key='auto_email_profile_id',
    )
    schedule_response = api_request('GET', f'/profiles/{int(auto_pid)}/email-schedule')
    schedule = (schedule_response or {}).get('schedule') or {}
    with st.form(f'auto_email_schedule_form_{int(auto_pid)}'):
        auto_email = st.text_input('Adresse Gmail de réception', value=schedule.get('recipient_email', ''))
        auto_enabled = st.checkbox('Activer les envois automatiques', value=bool(schedule.get('enabled', False)))
        c1, c2 = st.columns(2)
        with c1:
            auto_hour = st.number_input('Heure (Maroc)', min_value=0, max_value=23,
                                        value=int(schedule.get('send_hour', 9)))
            auto_limit = st.selectbox('Nombre maximal d’offres', [1, 3, 5, 10, 20],
                index=[1, 3, 5, 10, 20].index(int(schedule.get('max_jobs', 5)))
                if int(schedule.get('max_jobs', 5)) in [1, 3, 5, 10, 20] else 2)
        with c2:
            auto_minute = st.number_input('Minute', min_value=0, max_value=59,
                                          value=int(schedule.get('send_minute', 0)))
            auto_min_score = st.slider('Score minimum automatique', 0, 100,
                                      value=int(schedule.get('min_score', 0)))
        saved = st.form_submit_button('Enregistrer la programmation', type='primary')
    if saved:
        if not auto_email.strip() or '@' not in auto_email:
            st.warning('Saisis une adresse e-mail valide.')
        else:
            response = api_request('PUT', f'/profiles/{int(auto_pid)}/email-schedule', json={
                'email': auto_email.strip(), 'enabled': auto_enabled,
                'send_hour': int(auto_hour), 'send_minute': int(auto_minute),
                'timezone': 'Africa/Casablanca', 'max_jobs': int(auto_limit),
                'min_score': float(auto_min_score),
            })
            if response is not None:
                st.success('Programmation enregistrée. Le worker doit être démarré.')
    if schedule:
        st.caption(f"Dernière tentative : {schedule.get('last_attempt_date') or 'aucune'} · "
                   f"État : {schedule.get('last_status') or 'en attente'}")
        if schedule.get('last_error'):
            st.warning('Le dernier envoi a échoué. Consulte les logs du worker.')

with tab_analytics:
    render_dashboard()