import json
import os
import time
from datetime import datetime
import streamlit as st
from pydantic import BaseModel, Field

# Google GenAI SDK
from google import genai
from google.genai import types

# OpenAI SDK (käytetään sekä OpenAI:lle että Groqille, koska Groq on yhteensopiva)
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# Yritetään ladata dotenv paikallista kehitystä varten, jos se on asennettu
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ==============================================================================
# 1. SOVELLUKSEN JA SIVUN ASETUKSET
# ==============================================================================
st.set_page_config(
    page_title="MVA AI Muutosvaikutusanalyysi",
    layout="wide"
)

# Luetaan API-avaimet Streamlit Secretsistä tai ympäristömuuttujista
GEMINI_API_KEY = ""
if "GEMINI_API_KEY" in st.secrets:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
else:
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

OPENAI_API_KEY = ""
if "OPENAI_API_KEY" in st.secrets:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
else:
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

GROQ_API_KEY = ""
if "GROQ_API_KEY" in st.secrets:
    GROQ_API_KEY = st.secrets["GROQ_API_KEY"]
else:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# ==============================================================================
# 2. MVA ARCHITECTURE DATA LOADER (Hakee aina skriptin omasta kansiosta)
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

# Ladataan data muistiin
MVA_DATA = load_mva_data()

if MVA_DATA is None:
    st.stop()

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
        description="Validia Graphviz DOT-koodia riippuvuuskartan visualisointiin. Värjää suoran vaikutuksen solmut tumman punaisella / pehmeän punaisella, epäsuorat keltaisella ja koskemattomat maltillisen harmaalla. Käytä rankdir=LR ja varmista tummaan teemaan sopivat tekstivärit solmuissa."
    )

# ==============================================================================
# 4. SIVUPALKKI (SIDEBAR) - TILA & SKENAARIOT
# ==============================================================================
st.sidebar.title("Asetukset")

# Tekoälyntarjoajan valinta
ai_provider = st.sidebar.selectbox(
    "Valitse tekoälymalli",
    ["Google Gemini", "OpenAI ChatGPT", "Groq (Llama 3)"]
)

# Tarkistetaan valitun tarjoajan API-avain automaattisesti taustalta
if ai_provider == "Google Gemini":
    if GEMINI_API_KEY:
        st.sidebar.success("Gemini API-avain aktiivinen")
    else:
        st.sidebar.error("Gemini API-avain puuttuu (Aseta `GEMINI_API_KEY` Streamlit Secretsiin)")
    st.sidebar.info("API-versio: `v1` (Stabiili)")
elif ai_provider == "OpenAI ChatGPT":
    if OPENAI_API_KEY:
        st.sidebar.success("ChatGPT API-avain aktiivinen")
    else:
        st.sidebar.error("ChatGPT API-avain puuttuu (Aseta `OPENAI_API_KEY` Streamlit Secretsiin)")
    st.sidebar.info("Käytetty malli: `gpt-4o`")
else:
    if GROQ_API_KEY:
        st.sidebar.success("Groq API-avain aktiivinen")
    else:
        st.sidebar.error("Groq API-avain puuttuu (Aseta `GROQ_API_KEY` Streamlit Secretsiin)")
    st.sidebar.info("Käytetty malli: `llama-3.3-70b-versatile`")

st.sidebar.markdown("---")
st.sidebar.subheader("Testiskenaariot")

scenario_choice = st.sidebar.selectbox(
    "Lataa valmis skenaario",
    [
        "Valitse skenaario...",
        "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin",
        "Skenaario 2: Laskutusmoottorin rajapintamuutos",
        "Kirjoita oma syöte"
    ]
)

scenario_texts = {
    "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin": 
        "Nykyinen Asiakashallinta (SYS-CRM) korvataan uudella pilvipohjaisella SaaS-järjestelmällä. Vanha SQL-suorarajapinta poistuu ja jatkossa tiedot siirretään REST API:n kautta erillisessä yöajossa.",
    "Skenaario 2: Laskutusmoottorin rajapintamuutos": 
        "Laskutusmoottorin (SYS-LASKU) rajapintaa päivitetään siten, että asiakastunnisteen muoto muuttuu numeerisesta UUID-muotoon. Vanha rajapinta poistetaan käytöstä 1kk siirtymäajalla."
}

# ==============================================================================
# 5. PÄÄNÄKYMÄ (MAIN AREA)
# ==============================================================================
st.title("MVA AI Muutosvaikutusanalyysi (PoC)")
st.caption("Tekoälyavusteinen arkkitehtuurianalyysi kehysriippumattoman MVA-mallin pohjalta | YAMK Opinnäytetyö")

default_text = ""
if scenario_choice in scenario_texts:
    default_text = scenario_texts[scenario_choice]

change_proposal = st.text_area(
    "Syötä ehdotettu arkkitehtuurimuutos tai järjestelmävaihto:",
    value=default_text,
    height=120,
    placeholder="Kuvaile muutos, esim. 'Järjestelmä X korvataan uudella rajapinnalla...'"
)

run_button = st.button("Aja muutosvaikutusanalyysi", type="primary", use_container_width=True)

if "analysis_result" not in st.session_state:
    st.session_state.analysis_result = None

# ==============================================================================
# 6. ANALYYSIN SUORITTAMINEN VALITULLA API:LLA
# ==============================================================================
if run_button:
    if ai_provider == "Google Gemini" and not GEMINI_API_KEY:
        st.error("GEMINI_API_KEY puuttuu! Lisää se Streamlit Cloudin Secrets-asetuksiin.")
    elif ai_provider == "OpenAI ChatGPT" and not OPENAI_API_KEY:
        st.error("OPENAI_API_KEY puuttuu! Lisää se Streamlit Cloudin Secrets-asetuksiin.")
    elif ai_provider == "Groq (Llama 3)" and not GROQ_API_KEY:
        st.error("GROQ_API_KEY puuttuu! Lisää se Streamlit Cloudin Secrets-asetuksiin.")
    elif not change_proposal.strip():
        st.warning("Syötä muutosehdotus tekstikenttään.")
    else:
        status_container = st.empty()
        status_container.info(f"Tekoäly ({ai_provider}) analysoi MVA-riippuvuuksia ja laskee vaikutuksia...")

        json_mva_str = json.dumps(MVA_DATA, ensure_ascii=False, indent=2)
        system_instruction = (
            "Olet kokenut kokonaisarkkitehti (Enterprise Architect).\n"
            "Tehtäväsi on suorittaa tarkka muutosvaikutusanalyysi annetun Minimum Viable Architecture (MVA) -JSON-datan pohjalta.\n\n"
            "Arvioi muutosehdotuksen vaikutuksia suoriin ja epäsuoriin riippuvuuksiin.\n"
            "Muodosta laadukas Graphviz DOT -koodi, joka kuvaa koko järjestelmäkentän ja korostaa muutosalueet väreillä.\n"
            "Palauta vastauksesi tiukasti annetussa JSON-muodossa."
        )

        prompt = (
            f"TÄSSÄ ON ORGANISAATION MVA-ARKKITEHTUURIDATA:\n"
            f"```json\n{json_mva_str}\n```\n\n"
            f"EHDOTETTU ARKKITEHTUURIMUUTOS:\n"
            f"{change_proposal}\n\n"
            f"Suorita muutosvaikutusanalyysi MVA-datan pohjalta."
        )

        success = False

        # --- GOOGLE GEMINI KÄSITTELY ---
        if ai_provider == "Google Gemini":
            client = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options={'api_version': 'v1'}
            )
            model_variants = ["gemini-1.5-flash", "models/gemini-1.5-flash", "gemini-2.0-flash"]
            
            for model_name in model_variants:
                try:
                    response = client.models.generate_content(
                        model=model_name,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            system_instruction=system_instruction,
                            response_mime_type="application/json",
                            response_schema=ImpactAnalysisResult,
                            temperature=0.2,
                        ),
                    )
                    st.session_state.analysis_result = response.parsed
                    st.session_state.used_model = model_name
                    status_container.success(f"Analyysi valmis! (Malli: `{model_name}`)")
                    time.sleep(1)
                    success = True
                    st.rerun()
                    break

                except Exception as e:
                    error_str = str(e)
                    if "404" in error_str:
                        continue
                    elif "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                        status_container.warning("API-ilmaisraja saavutettu. Odotetaan 10 sekuntia ennen retrya...")
                        time.sleep(10)
                    else:
                        status_container.error(f"Virhe API-kutsussa: {error_str}")
                        break

        # --- OPENAI CHATGPT KÄSITTELY ---
        elif ai_provider == "OpenAI ChatGPT":
            if OpenAI is None:
                status_container.error("OpenAI-kirjastoa ei ole asennettu. Asenna komennolla `pip install openai`.")
            else:
                try:
                    openai_client = OpenAI(api_key=OPENAI_API_KEY)
                    completion = openai_client.beta.chat.completions.parse(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": prompt}
                        ],
                        response_format=ImpactAnalysisResult,
                        temperature=0.2,
                    )
                    st.session_state.analysis_result = completion.choices[0].message.parsed
                    st.session_state.used_model = "gpt-4o"
                    status_container.success("Analyysi valmis! (Malli: `gpt-4o`)")
                    time.sleep(1)
                    success = True
                    st.rerun()
                except Exception as e:
                    status_container.error(f"Virhe OpenAI API-kutsussa: {str(e)}")

        # --- GROQ KÄSITTELY ---
        elif ai_provider == "Groq (Llama 3)":
            if OpenAI is None:
                status_container.error("OpenAI-kirjastoa ei ole asennettu (Groq käyttää samaa kirjastoa). Asenna komennolla `pip install openai`.")
            else:
                try:
                    groq_client = OpenAI(
                        api_key=GROQ_API_KEY,
                        base_url="https://api.groq.com/openai/v1"
                    )
                    
                    schema_json_str = json.dumps(ImpactAnalysisResult.model_json_schema(), ensure_ascii=False, indent=2)
                    groq_prompt = (
                        f"{prompt}\n\n"
                        f"VASTAUSVAATIMUS: Palauta vastauksesi TÄSMÄLLEEN seuraavan JSON-skeeman mukaisena objektina:\n"
                        f"```json\n{schema_json_str}\n```"
                    )

                    completion = groq_client.chat.completions.create(
                        model="llama-3.3-70b-versatile",
                        messages=[
                            {"role": "system", "content": system_instruction},
                            {"role": "user", "content": groq_prompt}
                        ],
                        response_format={"type": "json_object"},
                        temperature=0.2,
                    )
                    
                    raw_content = completion.choices[0].message.content
                    parsed_data = json.loads(raw_content)
                    st.session_state.analysis_result = ImpactAnalysisResult(**parsed_data)
                    
                    st.session_state.used_model = "llama-3.3-70b-versatile (Groq)"
                    status_container.success("Analyysi valmis! (Malli: `llama-3.3-70b-versatile`)")
                    time.sleep(1)
                    success = True
                    st.rerun()
                except Exception as e:
                    status_container.error(f"Virhe Groq API-kutsussa: {str(e)}")

        if not success and "analysis_result" not in st.session_state:
            status_container.error("Analyysin suorittaminen epäonnistui tarkista API-avain ja verkkoyhteys.")

# ==============================================================================
# 7. TULOSTEN ESITTÄMINEN
# ==============================================================================
if st.session_state.analysis_result is not None:
    res: ImpactAnalysisResult = st.session_state.analysis_result
    used_model_name = st.session_state.get("used_model", "tuntematon-malli")

    st.markdown("---")
    st.header("Analyysin tulokset")

    col1, col2, col3 = st.columns(3)

    col1.metric("Kokonaisriskitaso", res.overall_risk)
    col2.metric("Vaikutuksen alaiset järjestelmät", f"{res.affected_systems_count} / {len(MVA_DATA['systems'])} kpl")
    col3.metric("Käytetty malli", used_model_name)

    if res.overall_risk == "KORKEA":
        st.error(f"**Yhteenveto:** {res.summary}")
    elif res.overall_risk == "KOHTALAINEN":
        st.warning(f"**Yhteenveto:** {res.summary}")
    else:
        st.success(f"**Yhteenveto:** {res.summary}")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("Vaikutuskartta (Riippuvuudet)")
        try:
            st.graphviz_chart(res.dot_graph, use_container_width=True)
        except Exception:
            st.info("Riippuvuuskaavion renderöinti epäonnistui. Näytetään raakakoodi:")
            st.code(res.dot_graph)

    with col_right:
        st.subheader("Vaikutukset järjestelmittäin")
        for sys_imp in res.impacts:
            with st.expander(f"**{sys_imp.system_name}** ({sys_imp.impact_type} vaikutus) - Riski: {sys_imp.risk_level}"):
                st.write(f"**Järjestelmä-ID:** `{sys_imp.system_id}`")
                st.write(f"**Riskitaso:** {sys_imp.risk_level}")
                st.write(f"**Kuvaus:** {sys_imp.description}")

    st.subheader("Suositellut toimenpiteet")
    for rec in res.recommendations:
        st.markdown(f"- {rec}")

    # ==========================================================================
    # 8. EVALUOINTIOSIO (LUKU 6 DATA)
    # ==========================================================================
    st.markdown("---")
    st.subheader("Asiantuntijan evaluointi (Opinnäytetyön aineistonkeruu)")
    st.caption("Arvioi tekoälyn tekemän muutosvaikutusanalyysin laatua ja luotettavuutta. Tiedot tallentuvat tutkimusaineistoksi.")

    with st.form("eval_form"):
        eval_rating = st.radio(
            "Osuiko tekoälyn arviointitulos ja riskitaso oikeaan?",
            ["Täysin oikein (5/5)", "Osittain oikein (3/5)", "Virheellinen/Puutteellinen (1/5)"],
            horizontal=True
        )
        eval_comments = st.text_area("Asiantuntijan kommentit, havaitut puutteet tai hallusinaatiot:")
        
        submit_eval = st.form_submit_button("Tallenna evaluointipalaute")

        if submit_eval:
            eval_entry = {
                "timestamp": datetime.now().isoformat(),
                "model": used_model_name,
                "scenario": scenario_choice,
                "proposal": change_proposal,
                "ai_overall_risk": res.overall_risk,
                "eval_rating": eval_rating,
                "eval_comments": eval_comments
            }

            file_path = "evaluations.json"
            evaluations = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        evaluations = json.load(f)
                except Exception:
                    evaluations = []

            evaluations.append(eval_entry)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(evaluations, f, ensure_ascii=False, indent=2)

            st.success("Palaute tallennettu onnistuneesti tiedostoon `evaluations.json`!")
