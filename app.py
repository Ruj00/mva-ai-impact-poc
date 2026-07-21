import json
import os
from datetime import datetime
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# Yritetään ladata dotenv paikallista kehitystä varten, jos se on asennettu
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==============================================================================
# 1. SOVELLUKSEN JA SIVUN ASETUKSET & API-AVAIN
# ==============================================================================
st.set_page_config(
    page_title="MVA AI Impact Analyzer",
    page_icon="🏗️",
    layout="wide"
)

# Luetaan API-avain ensin Streamlit Cloudin Secretsistä, sitten ympäristömuuttujista
API_KEY = ""
if "GEMINI_API_KEY" in st.secrets:
    API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    API_KEY = os.environ.get("GEMINI_API_KEY", "")

# ==============================================================================
# 2. MVA ARCHITECTURE DUMMY DATA (Kovakoodattu MVA-malli)
# ==============================================================================
MVA_DATA = {
    "organization": "Asiantuntijayritys Oy",
    "version": "1.2",
    "systems": [
        {
            "id": "SYS-CRM",
            "name": "Asiakashallinta (CRM)",
            "criticality": "KORKEA",
            "owner": "Myyntitiimi",
            "description": "Hallinnoi asiakastietoja ja myyntiputkea.",
            "upstream_dependencies": [],
            "downstream_dependencies": ["SYS-LASKU", "SYS-MARKETING"]
        },
        {
            "id": "SYS-LASKU",
            "name": "Laskutusmoottori",
            "criticality": "KRIITTINEN",
            "owner": "Taloushallinto",
            "description": "Laskujen luonti ja maksuvalvonta.",
            "upstream_dependencies": ["SYS-CRM"],
            "downstream_dependencies": ["SYS-ERP", "SYS-BI"]
        },
        {
            "id": "SYS-MARKETING",
            "name": "Markkinointiautomaatio",
            "criticality": "KOHTALAINEN",
            "owner": "Markkinointi",
            "description": "Sähköpostikampanjat ja liidien pisteytys.",
            "upstream_dependencies": ["SYS-CRM"],
            "downstream_dependencies": []
        },
        {
            "id": "SYS-ERP",
            "name": "Toiminnanohjaus (ERP)",
            "criticality": "KRIITTINEN",
            "owner": "Operatiivinen johto",
            "description": "Resursointi ja projektinhallinta.",
            "upstream_dependencies": ["SYS-LASKU"],
            "downstream_dependencies": ["SYS-BI"]
        },
        {
            "id": "SYS-BI",
            "name": "Raportointi & BI",
            "criticality": "MATALA",
            "owner": "Johtoryhmä",
            "description": "Liiketoiminta-analytiikka ja johdon raportit.",
            "upstream_dependencies": ["SYS-LASKU", "SYS-ERP"],
            "downstream_dependencies": []
        }
    ]
}

# ==============================================================================
# 3. PYDANTIC-MALLIT STRUCTURED OUTPUTIA VARTEN
# ==============================================================================
class SystemImpact(BaseModel):
    system_id: str = Field(description="Järjestelmän tunniste, esim. SYS-CRM")
    system_name: str = Field(description="Järjestelmän nimi")
    impact_type: str = Field(description="'Suora' tai 'Epäsuora'")
    risk_level: str = Field(description="'Punainen' (KORKEA), 'Keltainen' (KOHTALAINEN) tai 'Vihreä' (MATALA)")
    description: str = Field(description="Lyhyt perustelu vaikutukselle ja riskille")

class ImpactAnalysisResult(BaseModel):
    overall_risk: str = Field(description="Kokonaisriski: 'KORKEA', 'KOHTALAINEN' tai 'MATALA'")
    affected_systems_count: int = Field(description="Vaikutuksen alaisten järjestelmien kokonaismäärä")
    summary: str = Field(description="Tiivis 2-3 lauseen yhteenveto muutoksen vaikutuksista")
    impacts: list[SystemImpact] = Field(description="Lista kaikista järjestelmistä joihin muutos vaikuttaa")
    recommendations: list[str] = Field(description="3-5 konkreettista jatkotoimenpidesuositusta")
    dot_graph: str = Field(
        description="Validia Graphviz DOT-koodia riippuvuuskartan visualisointiin. Värjää suoran vaikutuksen solmut punaisella (fillcolor='#ffcccc'), epäsuorat keltaisella (fillcolor='#fff2cc') ja koskemattomat vihreällä (fillcolor='#e2efda'). Käytä rankdir=LR."
    )

# ==============================================================================
# 4. SIVUPALKKI (SIDEBAR) - ASETUKSET & SKENAARIOT
# ==============================================================================
st.sidebar.title("⚙️ PoC-Asetukset")

# Tilan ilmaisin API-avaimelle
if API_KEY:
    st.sidebar.success("🔑 Gemini API-avain aktiivinen")
else:
    st.sidebar.error("❌ API-avain puuttuu (Aseta `GEMINI_API_KEY` Streamlit Secretsiin)")

# Mallin valinta (Päivitetty toimivilla malleilla)
selected_model = st.sidebar.selectbox(
    "Valitse Gemini-malli",
    ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
    help="Flash on nopeampi kokeiluissa, Pro tarjoaa syvempää päättelykykyä."
)

st.sidebar.markdown("---")
st.sidebar.subheader("📋 Testiskenaariot")

scenario_choice = st.sidebar.selectbox(
    "Lataa valmis skenaario",
    [
        "Valitse skenaario...",
        "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin",
        "Skenaario 2: Laskutusmoottorin rajapintamuutos",
        "Kirjoita oma syöte"
    ]
)

# Pre-filled texts for scenarios
scenario_texts = {
    "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin": 
        "Nykyinen Asiakashallinta (SYS-CRM) korvataan uudella pilvipohjaisella SaaS-järjestelmällä. Vanha SQL-suorarajapinta poistuu ja jatkossa tiedot siirretään REST API:n kautta erillisessä yöajossa.",
    "Skenaario 2: Laskutusmoottorin rajapintamuutos": 
        "Laskutusmoottorin (SYS-LASKU) rajapintaa päivitetään siten, että asiakastunnisteen muoto muuttuu numeerisesta UUID-muotoon. Vanha rajapinta poistetaan käytöstä 1kk siirtymäajalla."
}

# ==============================================================================
# 5. PÄÄNÄKYMÄ (MAIN AREA)
# ==============================================================================
st.title("🏗️ MVA AI Muutosvaikutusanalyysi (PoC)")
st.caption("Tekoälyavusteinen arkkitehtuurianalyysi kehysriippumattoman MVA-mallin pohjalta | YAMK Opinnäytetyö")

# Default text logic
default_text = ""
if scenario_choice in scenario_texts:
    default_text = scenario_texts[scenario_choice]

change_proposal = st.text_area(
    "Syötä ehdotettu arkkitehtuurimuutos tai järjestelmävaihto:",
    value=default_text,
    height=120,
    placeholder="Kuvaile muutos, esim. 'Järjestelmä X korvataan uudella rajapinnalla...'"
)

run_button = st.button("🚀 Aja muutosvaikutusanalyysi", type="primary", use_container_width=True)

# Session state analysis persistence
if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

# ==============================================================================
# 6. ANALYYSIN SUORITTAMINEN GEMINI API:LLA
# ==============================================================================
if run_button:
    if not API_KEY:
        st.error("❌ GEMINI_API_KEY puuttuu! Lisää se Streamlit Cloudin Secrets-asetuksiin muodossa:\n`GEMINI_API_KEY = \"oma_api_avaimesi\"`")
    elif not change_proposal.strip():
        st.warning("⚠️ Syötä muutosehdotus tekstikenttään.")
    else:
        with st.spinner("Tekoäly analysoi MVA-riippuvuuksia ja laskee vaikutuksia..."):
            try:
                # Alustetaan client ladatulla API-avaimella
                client = genai.Client(api_key=API_KEY)

                system_instruction = """
                Olet kokenut kokonaisarkkitehti (Enterprise Architect). 
                Tehtäväsi on suorittaa tarkka muutosvaikutusanalyysi annetun Minimum Viable Architecture (MVA) -JSON-datan pohjalta.
                
                Arvioi muutosehdotuksen vaikutuksia suoriin ja epäsuoriin riippuvuuksiin.
                Muodosta laadukas Graphviz DOT -koodi, joka kuvaa koko järjestelmäkentän ja korostaa muutosalueet väreillä.
                Palauta vastauksesi tiukasti annetussa JSON-muodossa.
                """

                prompt = f"""
                TÄSSÄ ON ORGANISAATION MVA-ARKKITEHTUURIDATA:
                ```json
                {json.dumps(MVA_DATA, ensure_ascii=False, indent=2)}
