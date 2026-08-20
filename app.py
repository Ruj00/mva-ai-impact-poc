import json
import os
import time
from datetime import datetime
import streamlit as st
import psycopg2
from pydantic import BaseModel, Field
from styles import load_custom_css

# Ajetaan tyylit heti sivun konfiguroinnin jälkeen
load_custom_css()

# Google GenAI SDK
from google import genai
from google.genai import types

# OpenAI SDK (käytetään sekä OpenAI:lle että Groqille)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Yritetään ladata dotenv paikallista kehitystä varten
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==============================================================================
# 1. SOVELLUKSEN JA SIVUN ASETUKSET
# ==============================================================================
st.set_page_config(
    page_title="MVA AI Muutosvaikutusanalyysi & QA",
    layout="wide"
)

# Luetaan API-avaimet Streamlit Secretsistä tai ympäristömuuttujista
GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
OPENAI_API_KEY = st.secrets.get("OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
GROQ_API_KEY = st.secrets.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))

# ==============================================================================
# 2. MVA ARCHITECTURE DATA LOADER
# ==============================================================================
@st.cache_data
def load_mva_data(file_name="mva_architecture.json"):
    """Lataa MVA-arkkitehtuuridatan luotettavasti suoraan skriptin omasta kansiosta."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file_name)
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            st.error(f"Virhe arkkitehtuuridatan lukemisessa: {e}")
            return None
    else:
        st.error(f"Arkkitehtuuritiedostoa ei löytynyt polusta: {file_path}")
        return None

MVA_DATA = load_mva_data()
if MVA_DATA is None:
    st.stop()

# ==============================================================================
# 3. PYDANTIC-MALLIT STRUCTURED OUTPUTIA VARTEN (VAIN ANALYYSITILAAN)
# ==============================================================================
class SystemImpact(BaseModel):
    system_id: str = Field(description="Järjestelmän tunniste, esim. SYS-CRM")
    system_name: str = Field(description="Järjestelmän nimi")
    impact_type: str = Field(description="'Suora' tai 'Epäsuora'")
    risk_level: str = Field(description="'Punainen' (KORKEA), 'Keltainen' (KOHTALAINEN) tai 'Vihreä' (MATALA)")
    description: str = Field(description="Lyhyt perustelu vaikutukselle ja riskille")

class ImpactAnalysisResult(BaseModel):
    overall_risk: str = Field(description="Kokonaisriski: 'KORKEA', 'KOHTALAINEN' tai 'MATALA'")
    affected_systems_count: int = Field(description="Vaikutuksen alaiset järjestelmät kokonaismäärä")
    summary: str = Field(description="Tiivis 2-3 lauseen yhteenveto muutoksen vaikutuksista")
    strategic_alignment: str = Field(description="Arvio siitä, miten muutos tukee tai haastaa organisaation strategisia tavoitteita.")
    impacts: list[SystemImpact] = Field(description="Lista kaikista järjestelmistä joihin muutos vaikuttaa")
    recommendations: list[str] = Field(description="3-5 konkreettista jatkotoimenpidesuositusta")
    dot_graph: str = Field(
        description="Validia Graphviz DOT-koodia riippuvuuskartan visualisointiin. Värjää suoran vaikutuksen solmut tumman punaisella, epäsuorat keltaisella ja koskemattomat harmaalla. Käytä rankdir=LR."
    )

# ==============================================================================
# 4. SIVUPALKKI (SIDEBAR)
# ==============================================================================
st.sidebar.subheader("Mitä haluat tehdä?")
app_mode = st.sidebar.radio(
    "Valitse käyttötapa:",
    ["Kysy arkkitehtuurista (QA)", "Muutosvaikutusanalyysi"],
    help="Muutosvaikutusanalyysi analysoi järjestelmämuutosten riskejä ja riippuvuuksia. Kysy arkkitehtuurista -tilassa voit esittää vapaamuotoisia kysymyksiä nykyisestä MVA-datasta."
)

scenario_choice = "Kirjoita oma syöte"
scenario_texts = {
    "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin": 
        "Nykyinen Asiakashallinta (SYS-CRM) korvataan uudella pilvipohjaisella SaaS-järjestelmällä. Vanha SQL-suorarajapinta poistuu ja jatkossa tiedot siirretään REST API:n kautta erillisessä yöajossa.",
    "Skenaario 2: Laskutusmoottorin rajapintamuutos": 
        "Laskutusmoottorin (SYS-LASKU) rajapintaa päivitetään siten, että asiakastunnisteen muoto muuttuu numeerisesta UUID-muotoon. Vanha rajapinta poistetaan käytöstä 1kk siirtymäajalla.",
    "Skenaario 3: Uuden HR-järjestelmän käyttöönotto":
        "Olemassa olevaan arkkitehtuuriin tuodaan uusi HR- ja Osaamisenhallinta (SYS-HR), joka liitetään suoraan toiminnanohjaukseen ja keskitettyyn pääsynhallintaan."
}

if app_mode == "Muutosvaikutusanalyysi":
    st.sidebar.markdown("---")
    st.sidebar.subheader("Testiskenaariot")
    scenario_choice = st.sidebar.selectbox(
        "Lataa valmis skenaario",
        [
            "Valitse skenaario...",
            "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin",
            "Skenaario 2: Laskutusmoottorin rajapintamuutos",
            "Skenaario 3: Uuden HR-järjestelmän käyttöönotto",
            "Kirjoita oma syöte"
        ]
    )

# Malli- ja API-asetukset alhaalla
st.sidebar.markdown("---")
st.sidebar.subheader("Tekoälyasetukset")

ai_provider = st.sidebar.selectbox(
    "Valitse tekoälymalli",
    ["Groq (Llama 3)", "Google Gemini", "OpenAI ChatGPT"]
)

if ai_provider == "Groq (Llama 3)":
    if GROQ_API_KEY:
        st.sidebar.success("Groq API-avain aktiivinen")
    else:
        st.sidebar.error("Groq API-avain puuttuu")
elif ai_provider == "Google Gemini":
    if GEMINI_API_KEY:
        st.sidebar.success("Gemini API-avain aktiivinen")
    else:
        st.sidebar.error("Gemini API-avain puuttuu")
else:
    if OPENAI_API_KEY:
        st.sidebar.success("ChatGPT API-avain aktiivinen")
    else:
        st.sidebar.error("ChatGPT API-avain puuttuu")

# ==============================================================================
# 5. PÄÄNÄKYMÄ
# ==============================================================================
st.title("MVA AI Arkkitehtuuri-assistentti (PoC)")

if app_mode == "Muutosvaikutusanalyysi":
    default_text = scenario_texts.get(scenario_choice, "")
    user_input = st.text_area(
        "Syötä ehdotettu arkkitehtuurimuutos tai järjestelmävaihto:",
        value=default_text,
        height=120,
        placeholder="Kuvaile muutos..."
    )
    run_button = st.button("Aja muutosvaikutusanalyysi", type="primary", use_container_width=True
