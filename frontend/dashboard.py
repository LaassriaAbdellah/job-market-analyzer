
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st


API_URL = os.getenv(
    "API_URL",
    "http://127.0.0.1:8000"
).rstrip("/")


# ============================================================
# COMMUNICATION AVEC FASTAPI
# ============================================================

def get_data(endpoint):
    try:
        response = requests.get(
            f"{API_URL}{endpoint}",
            timeout=30
        )
        response.raise_for_status()
        return response.json()

    except requests.RequestException as exc:
        st.error(f"Erreur API ({endpoint}) : {exc}")
        return None


# ============================================================
# DASHBOARD ANALYTICS
# ============================================================

def render_dashboard():

    st.title("📊 Job Market Analytics")
    st.write(
        "Analyse des offres d'emploi collectées, "
        "des compétences recherchées et du matching intelligent."
    )

    # --------------------------------------------------------
    # 1. INDICATEURS GÉNÉRAUX
    # --------------------------------------------------------

    st.subheader("Vue générale")

    overview = get_data("/analytics/overview")

    if overview is not None:

        c1, c2, c3, c4 = st.columns(4)

        c1.metric(
            "Offres",
            overview.get("total_jobs", 0)
        )

        c2.metric(
            "Entreprises",
            overview.get("total_companies", 0)
        )

        c3.metric(
            "Sources",
            overview.get("total_sources", 0)
        )

        c4.metric(
            "Profils",
            overview.get("total_profiles", 0)
        )

    st.divider()

    # --------------------------------------------------------
    # 2. SOURCES ET COMPÉTENCES
    # --------------------------------------------------------

    col1, col2 = st.columns(2)

    with col1:

        st.subheader("Offres par source")

        sources = get_data("/analytics/sources")

        if sources:

            df_sources = pd.DataFrame(sources)

            df_sources["source"] = (
                df_sources["source"].astype(str)
            )

            df_sources["count"] = (
                pd.to_numeric(
                    df_sources["count"],
                    errors="raise"
                ).astype(int)
            )

            fig = go.Figure()

            fig.add_trace(
                go.Bar(
                    x=df_sources["source"].tolist(),
                    y=df_sources["count"].tolist(),
                    text=df_sources["count"].tolist(),
                    textposition="outside",
                    name="Offres"
                )
            )

            fig.update_layout(
                xaxis_title="Source",
                yaxis_title="Nombre d'offres",
                yaxis_type="linear",
                yaxis_range=[
                    0,
                    max(df_sources["count"].max() * 1.15, 1)
                ],
                height=420,
                showlegend=False
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key="analytics_sources"
            )

        elif sources == []:
            st.info("Aucune source disponible.")

    with col2:

        st.subheader("Compétences les plus demandées")

        skills = get_data("/analytics/skills")

        if skills:

            df_skills = pd.DataFrame(skills)

            df_skills["count"] = pd.to_numeric(
                df_skills["count"],
                errors="raise"
            ).astype(int)

            df_skills = (
                df_skills
                .sort_values("count", ascending=True)
                .tail(15)
            )

            fig = go.Figure(
                go.Bar(
                    x=df_skills["count"].tolist(),
                    y=df_skills["skill"].astype(str).tolist(),
                    orientation="h",
                    text=df_skills["count"].tolist(),
                    textposition="outside"
                )
            )

            fig.update_layout(
                xaxis_title="Nombre d'offres",
                yaxis_title="Compétence",
                xaxis_type="linear",
                height=420
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key="analytics_skills"
            )

        elif skills == []:
            st.info("Aucune compétence disponible.")

    st.divider()

    # --------------------------------------------------------
    # 3. ANALYSE DÉTAILLÉE DU MARCHÉ
    # --------------------------------------------------------

    st.header("Analyse détaillée du marché")

    col3, col4 = st.columns(2)

    # Types de contrat
    with col3:

        st.subheader("Répartition par type de contrat")

        contracts = get_data("/analytics/contracts")

        if contracts:

            df_contracts = pd.DataFrame(contracts)

            df_contracts["count"] = pd.to_numeric(
                df_contracts["count"],
                errors="raise"
            ).astype(int)

            fig = go.Figure(
                data=[
                    go.Pie(
                        labels=(
                            df_contracts["contract_type"]
                            .astype(str)
                            .tolist()
                        ),
                        values=df_contracts["count"].tolist(),
                        hole=0.4,
                        textinfo="percent+value"
                    )
                ]
            )

            fig.update_layout(height=430)

            st.plotly_chart(
                fig,
                use_container_width=True,
                key="analytics_contracts"
            )

        elif contracts == []:
            st.info("Aucune donnée sur les contrats.")

    # Localisations
    with col4:

        st.subheader("Top 15 des localisations")

        locations = get_data("/analytics/locations")

        if locations:

            df_locations = pd.DataFrame(locations)

            df_locations["count"] = pd.to_numeric(
                df_locations["count"],
                errors="raise"
            ).astype(int)

            df_locations = (
                df_locations
                .sort_values("count", ascending=True)
                .tail(15)
            )

            fig = go.Figure(
                go.Bar(
                    x=df_locations["count"].tolist(),
                    y=df_locations["location"].astype(str).tolist(),
                    orientation="h",
                    text=df_locations["count"].tolist(),
                    textposition="outside"
                )
            )

            fig.update_layout(
                xaxis_title="Nombre d'offres",
                yaxis_title="Localisation",
                xaxis_type="linear",
                height=430
            )

            st.plotly_chart(
                fig,
                use_container_width=True,
                key="analytics_locations"
            )

        elif locations == []:
            st.info("Aucune localisation disponible.")

    st.divider()

    # --------------------------------------------------------
    # 4. ANALYSE DU MATCHING INTELLIGENT
    # --------------------------------------------------------

    st.header("Analyse du matching intelligent")

    profile_id = st.number_input(
        "Identifiant du profil à analyser",
        min_value=1,
        value=6,
        step=1,
        key="analytics_profile_id"
    )

    matching = get_data(
        f"/analytics/matching/{profile_id}"
    )

    if matching is None:
        return

    # Indicateurs de matching
    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Offres évaluées",
        matching.get("total_matches", 0)
    )

    c2.metric(
        "Score moyen",
        f"{matching.get('average_score', 0):.2f} %"
    )

    c3.metric(
        "Meilleur score",
        f"{matching.get('max_score', 0):.2f} %"
    )

    scores = matching.get("scores", [])

    if not scores:
        st.info(
            "Aucun matching enregistré pour ce profil. "
            "Lance d'abord le matching."
        )
        return

    # Conversion des scores en valeurs numériques
    numeric_scores = pd.to_numeric(
        pd.Series(scores),
        errors="coerce"
    ).dropna()

    numeric_scores = numeric_scores[
        numeric_scores.between(0, 100)
    ]

    if numeric_scores.empty:
        st.warning("Aucun score numérique valide.")
        return

    # Création des intervalles de 10 %
    counts, edges = np.histogram(
        numeric_scores,
        bins=np.arange(0, 110, 10)
    )

    labels = [
        f"{int(edges[i])}–{int(edges[i + 1])} %"
        for i in range(len(counts))
    ]

    st.caption(
        f"Total dans l'histogramme : "
        f"{int(counts.sum())} offres"
    )

    # Histogramme des scores
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=counts.tolist(),
                text=counts.tolist(),
                textposition="outside",
                name="Offres"
            )
        ]
    )

    fig.update_layout(
        xaxis_title="Intervalle de score",
        yaxis_title="Nombre d'offres",
        xaxis_type="category",
        yaxis_type="linear",
        height=430,
        showlegend=False
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        key="analytics_matching_distribution"
    )


# ============================================================
# EXÉCUTION INDÉPENDANTE
# ============================================================

if __name__ == "__main__":
    st.set_page_config(
        page_title="Job Market Analytics",
        page_icon="📊",
        layout="wide"
    )

    render_dashboard()
