Python
import json
import os
from datetime import datetime
import streamlit as st
from pydantic import BaseModel, Field
from google import genai
from google.genai import types

# ==============================================================================
# 1. SOVELLUKSEN JA SIVUN ASETUKSET
# ==============================================================================
st.set_page_config(
    page_title="MVA AI Impact Analyzer",
    page_icon="🏗️",
    layout="wide"
)

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

# Gemini API Key input
api_key = st.sidebar.text_input(
    "Google Gemini API Key",
    type="password",
    help="Syötä Google AI Studio API key. Jos tyhjä, koodi yrittää lukea GEMINI_API_KEY-ympäristömuuttujaa."
)
if not api_key:
    api_key = os.environ.get("GEMINI_API_KEY", "")

# Mallin valinta
selected_model = st.sidebar.selectbox(
    "Valitse Gemini-malli",
    ["gemini-1.5-flash", "gemini-1.5-pro"],
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
    if not api_key:
        st.error("❌ Syötä Gemini API Key sivupalkkiin ennen analyysin ajamista.")
    elif not change_proposal.strip():
        st.warning("⚠️ Syötä muutosehdotus tekstikenttään.")
    else:
        with st.spinner("Tekoäly analysoi MVA-riippuvuuksia ja laskee vaikutuksia..."):
            try:
                # Alustetaan uusi google-genai Client
                client = genai.Client(api_key=api_key)

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
                ```

                EHDOTETTU ARKKITEHTUURIMUUTOS:
                "{change_proposal}"

                Suorita muutosvaikutusanalyysi MVA-datan pohjalta.
                """

                # API-kutsu Structured Output -määrityksellä
                response = client.models.generate_content(
                    model=selected_model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=ImpactAnalysisResult,
                        temperature=0.2,
                    ),
                )

                # Tallennetaan jäsennelty vastaus Session Stateen
                st.session_state.analysis_result = response.parsed
                st.success("Analysis valmis!")

            except Exception as e:
                st.error(f"Virhe API-kutsussa: {str(e)}")

# ==============================================================================
# 7. TULOSTEN ESITTÄMINEN
# ==============================================================================
if st.session_state.analysis_result is not None:
    res: ImpactAnalysisResult = st.session_state.analysis_result

    st.markdown("---")
    st.header("📊 Analyysin tulokset")

    # Metrics Row
    col1, col2, col3 = st.columns(3)

    risk_colors = {"KORKEA": "🔴", "KOHTALAINEN": "🟡", "MATALA": "🟢"}
    risk_icon = risk_colors.get(res.overall_risk, "⚪")

    col1.metric("Kokonaisriskitaso", f"{risk_icon} {res.overall_risk}")
    col2.metric("Vaikutuksen alaiset järjestelmät", f"{res.affected_systems_count} / {len(MVA_DATA['systems'])} pcs")
    col3.metric("Käytetty malli", selected_model)

    # Yhteenvetoboksi
    if res.overall_risk == "KORKEA":
        st.error(f"**Yhteenveto:** {res.summary}")
    elif res.overall_risk == "KOHTALAINEN":
        st.warning(f"**Yhteenveto:** {res.summary}")
    else:
        st.success(f"**Yhteenveto:** {res.summary}")

    # Visualisointi & Yksityiskohdat rinnakkain
    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.subheader("🕸️ Vaikutuskartta (Riippuvuudet)")
        try:
            st.graphviz_chart(res.dot_graph, use_container_width=True)
        except Exception:
            st.info("Riippuvuuskaavion renderöinti epäonnistui. Näytetään raakakoodi:")
            st.code(res.dot_graph)

    with col_right:
        st.subheader("📋 Vaikutukset järjestelmittäin")
        for sys_imp in res.impacts:
            badge = "🔴" if sys_imp.risk_level == "Punainen" else ("🟡" if sys_imp.risk_level == "Keltainen" else "🟢")
            with st.expander(f"{badge} **{sys_imp.system_name}** ({sys_imp.impact_type} vaikutus)"):
                st.write(f"**Järjestelmä-ID:** `{sys_imp.system_id}`")
                st.write(f"**Riskitaso:** {sys_imp.risk_level}")
                st.write(f"**Kuvaus:** {sys_imp.description}")

    st.subheader("💡 Suositellut toimenpiteet")
    for rec in res.recommendations:
        st.markdown(f"- {rec}")

    # ==========================================================================
    # 8. EVALUOINTIOSIO (LUKU 6 DATA)
    # ==========================================================================
    st.markdown("---")
    st.subheader("🧪 Asiantuntijan evaluointi (Opinnäytetyön aineistonkeruu)")
    st.caption("Arvioi tekoälyn tekemän muutosvaikutusanalyysin laatua ja luotettavuutta. Tiedot tallentuvat tutkimusaineistoksi.")

    with st.form("eval_form"):
        eval_rating = st.radio(
            "Osuiko tekoälyn arviointitulos ja riskitaso oikeaan?",
            ["Täysin oikein (5/5)", "Osittain oikein (3/5)", "Virheellinen/Puutteellinen (1/5)"],
            horizontal=True
        )
        eval_comments = st.text_area("Asiantuntijan kommentit, havaitut puutteet tai hallusinaatiot:")
        
        submit_eval = st.form_submit_button("💾 Tallenna evaluointipalaute")

        if submit_eval:
            eval_entry = {
                "timestamp": datetime.now().isoformat(),
                "model": selected_model,
                "scenario": scenario_choice,
                "proposal": change_proposal,
                "ai_overall_risk": res.overall_risk,
                "eval_rating": eval_rating,
                "eval_comments": eval_comments
            }

            # Tallennettaan local json-tiedostoon
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

            st.success("✅ Palaute tallennettu onnistuneesti tiedostoon `evaluations.json`!"