import json
import os
import time
from datetime import datetime
import psycopg2
from pydantic import BaseModel, Field
import streamlit as st
from styles import load_custom_css

# ==============================================================================
# 1. SOVELLUKSEN JA SIVUN ASETUKSET
# ==============================================================================
st.set_page_config(page_title="MVA AI Muutosvaikutusanalyysi & QA", layout="wide")

# Ajetaan tyylit heti sivun konfiguroinnin jälkeen
load_custom_css()

# Google GenAI SDK
from google import genai
from google.genai import types

# OpenAI SDK (Käytetään OpenAI:lle, Groqille ja OpenRouterille)
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

# Luetaan API-avaimet Streamlit Secretsistä tai ympäristömuuttujista
GEMINI_API_KEY = st.secrets.get(
    "GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", "")
)
OPENAI_API_KEY = st.secrets.get(
    "OPENAI_API_KEY", os.environ.get("OPENAI_API_KEY", "")
)
GROQ_API_KEY = st.secrets.get(
    "GROQ_API_KEY", os.environ.get("GROQ_API_KEY", "")
)
OPENROUTER_API_KEY = st.secrets.get(
    "OPENROUTER_API_KEY", os.environ.get("OPENROUTER_API_KEY", "")
)


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
  risk_level: str = Field(
      description=(
          "'Punainen' (KORKEA), 'Keltainen' (KOHTALAINEN) tai 'Vihreä' (MATALA)"
      )
  )
  description: str = Field(description="Lyhyt perustelu vaikutukselle ja riskille")


class ImpactAnalysisResult(BaseModel):
  overall_risk: str = Field(
      description="Kokonaisriski: 'KORKEA', 'KOHTALAINEN' tai 'MATALA'"
  )
  affected_systems_count: int = Field(
      description="Vaikutuksen alaiset järjestelmät kokonaismäärä"
  )
  summary: str = Field(
      description="Tiivis 2-3 lauseen yhteenveto muutoksen vaikutuksista"
  )
  strategic_alignment: str = Field(
      description=(
          "Arvio siitä, miten muutos tukee tai haastaa organisaation strategisia"
          " tavoitteita."
      )
  )
  impacts: list[SystemImpact] = Field(
      description="Lista kaikista järjestelmistä joihin muutos vaikuttaa"
  )
  recommendations: list[str] = Field(
      description="3-5 konkreettista jatkotoimenpidesuositusta"
  )
  dot_graph: str = Field(
      description=(
          "Validia Graphviz DOT-koodia riippuvuuskartan visualisointiin. Värjää"
          " suoran vaikutuksen solmut tumman punaisella, epäsuorat keltaisella"
          " ja koskemattomat harmaalla. Käytä rankdir=LR."
      )
  )


# ==============================================================================
# 4. SIVUPALKKI (SIDEBAR)
# ==============================================================================
st.sidebar.subheader("Mitä haluat tehdä?")
app_mode = st.sidebar.radio(
    "Valitse käyttötapa:",
    ["Kysy arkkitehtuurista (QA)", "Muutosvaikutusanalyysi"],
    help=(
        "Muutosvaikutusanalyysi analysoi järjestelmämuutosten riskejä ja"
        " riippuvuuksia. Kysy arkkitehtuurista -tilassa voit esittää"
        " vapaamuotoisia kysymyksiä nykyisestä MVA-datasta."
    ),
)

scenario_choice = "Kirjoita oma syöte"
scenario_texts = {
    "Skenaario 1: CRM-järjestelmän vaihto SaaS-malliin": (
        "Nykyinen Asiakashallinta (SYS-CRM) korvataan uudella pilvipohjaisella"
        " SaaS-järjestelmällä. Vanha SQL-suorarajapinta poistuu ja jatkossa"
        " tiedot siirretään REST API:n kautta erillisessä yöajossa."
    ),
    "Skenaario 2: Laskutusmoottorin rajapintamuutos": (
        "Laskutusmoottorin (SYS-LASKU) rajapintaa päivitetään siten, että"
        " asiakastunnisteen muoto muuttuu numeerisesta UUID-muotoon. Vanha"
        " rajapinta poistetaan käytöstä 1kk siirtymäajalla."
    ),
    "Skenaario 3: Uuden HR-järjestelmän käyttöönotto": (
        "Olemassa olevaan arkkitehtuuriin tuodaan uusi HR- ja Osaamisenhallinta"
        " (SYS-HR), joka liitetään suoraan toiminnanohjaukseen ja keskitettyyn"
        " pääsynhallintaan."
    ),
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
          "Kirjoita oma syöte",
      ],
  )

st.sidebar.markdown("---")
st.sidebar.subheader("Tekoälyasetukset")

ai_provider = st.sidebar.selectbox(
    "Valitse tekoälymalli",
    [
        "OpenRouter (Ilmainen)",
        "Google Gemini",
        "Groq (Llama 3)",
        "OpenAI ChatGPT",
    ],
)

if ai_provider == "OpenRouter (Ilmainen)":
  if OPENROUTER_API_KEY:
    st.sidebar.success("OpenRouter API-avain aktiivinen")
  else:
    st.sidebar.error("OpenROUTER API-avain puuttuu")
elif ai_provider == "Google Gemini":
  if GEMINI_API_KEY:
    st.sidebar.success("Gemini API-avain aktiivinen")
  else:
    st.sidebar.error("Gemini API-avain puuttuu")
elif ai_provider == "Groq (Llama 3)":
  if GROQ_API_KEY:
    st.sidebar.success("Groq API-avain aktiivinen")
  else:
    st.sidebar.error("Groq API-avain puuttuu")
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
      placeholder="Kuvaile muutos...",
  )
  run_button = st.button(
      "Aja muutosvaikutusanalyysi", type="primary", use_container_width=True
  )
else:
  user_input = st.text_area(
      "Kysy mitä tahansa organisaation kokonaisarkkitehtuurista:",
      height=100,
      placeholder=(
          "Esim. Mitkä järjestelmät tukeutuvat CRM:ään ja kuka omistaa"
          " taloushallinnon ratkaisut?"
      ),
  )
  run_button = st.button(
      "Lähetä kysymys", type="primary", use_container_width=True
  )

# Alustetaan session state -muuttujat
if "analysis_result" not in st.session_state:
  st.session_state.analysis_result = None
if "qa_result" not in st.session_state:
  st.session_state.qa_result = None

# ==============================================================================
# 6. ANALYYSIN TAI KYSELYN SUORITTAMINEN
# ==============================================================================
if run_button:
  if ai_provider == "OpenRouter (Ilmainen)" and not OPENROUTER_API_KEY:
    st.error("OPENROUTER_API_KEY puuttuu secrets-tiedostosta!")
  elif ai_provider == "Google Gemini" and not GEMINI_API_KEY:
    st.error("GEMINI_API_KEY puuttuu secrets-tiedostosta!")
  elif ai_provider == "Groq (Llama 3)" and not GROQ_API_KEY:
    st.error("GROQ_API_KEY puuttuu secrets-tiedostosta!")
  elif ai_provider == "OpenAI ChatGPT" and not OPENAI_API_KEY:
    st.error("OPENAI_API_KEY puuttuu secrets-tiedostosta!")
  elif not user_input.strip():
    st.warning("Syötä tekstikenttään muutosehdotus tai kysymys.")
  else:
    status_container = st.empty()

    # Tiivistetty JSON ilman sisennystä säästää huomattavasti tokeneita
    json_mva_str = json.dumps(MVA_DATA, ensure_ascii=False)

    # Tyhjennetään aiemmat tulokset ajon alussa
    st.session_state.analysis_result = None
    st.session_state.qa_result = None

    if app_mode == "Muutosvaikutusanalyysi":
      status_container.info(
          f"Tekoäly ({ai_provider}) analysoi MVA-riippuvuuksia..."
      )
      system_instruction = (
          "Olet kokenut kokonaisarkkitehti (Enterprise Architect).\nTehtäväsi"
          " on suorittaa tarkka muutosvaikutusanalyysi annetun Minimum Viable"
          " Architecture (MVA) -JSON-datan pohjalta.\nPalauta vastauksesi"
          " tiukasti annetussa JSON-muodossa."
      )
      prompt = (
          f"TÄSSÄ ON ORGANISAATION MVA-ARKKITEHTUURIDATA JA STRATEGIA:\n```json\n{json_mva_str}\n```\n\nEHDOTETTU"
          f" ARKKITEHTUURIMUUTOS:\n{user_input}\n\nSuorita kattava"
          " muutosvaikutusanalyysi MVA-datan pohjalta."
      )
    else:
      status_container.info(
          f"Tekoäly ({ai_provider}) hakee vastausta arkkitehtuuridatasta..."
      )
      system_instruction = (
          "Olet kokenut ja asiantunteva kokonaisarkkitehti (Enterprise"
          " Architect).\nVastaa käyttäjän esittämään kysymykseen nojautuen"
          " AINOASTAAN annettuun MVA-arkkitehtuuridataan.\nEsitä vastaus"
          " selkeästi, ammattimaisesti ja jäsennellysti (käytä tarvittaessa"
          " taulukoita, ranskalaisia viivoja tai lihavointeja).\nJos kysyttyä"
          " tietoa ei löydy annetusta datasta, ilmoita siitä selkeästi äläkä"
          " keksi tietoja."
      )
      prompt = (
          f"ORGANISAATION MVA-ARKKITEHTUURIDATA JA STRATEGIA:\n```json\n{json_mva_str}\n```\n\nKÄYTTÄJÄN"
          f" KYSYMYS:\n{user_input}"
      )

    success = False

    # --- OPENROUTER (ILMAINEN) ---
    if ai_provider == "OpenRouter (Ilmainen)":
      if OpenAI is None:
        status_container.error("OpenAI-kirjastoa ei ole asennettu.")
      else:
        try:
          openrouter_client = OpenAI(
              base_url="https://openrouter.ai/api/v1",
              api_key=OPENROUTER_API_KEY,
              timeout=30.0,
          )

          # Päivitetyt ja tällä hetkellä toimivat ilmaiset OpenRouter-mallit
          free_models = [
              "google/gemini-2.0-flash-lite-preview-02-05:free",
              "meta-llama/llama-3.1-8b-instruct:free",
              "deepseek/deepseek-r1:free",
              "qwen/qwen-2.5-72b-instruct:free",
          ]

          for model_name in free_models:
            try:
              if app_mode == "Muutosvaikutusanalyysi":
                schema_json_str = json.dumps(
                    ImpactAnalysisResult.model_json_schema(),
                    ensure_ascii=False,
                )
                or_prompt = (
                    f"{prompt}\n\nVastaa TÄSMÄLLEEN ja AINOASTAAN seuraavan"
                    " JSON-skeeman mukaisessa"
                    f" JSON-muodossa:\n```json\n{schema_json_str}\n```"
                )

                completion = openrouter_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": or_prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=0.2,
                    max_tokens=2048,
                )
                raw_content = (
                    completion.choices[0].message.content.strip()
                )
                if raw_content.startswith("```"):
                  raw_content = (
                      raw_content.replace("```json", "")
                      .replace("```", "")
                      .strip()
                  )
                parsed_data = json.loads(raw_content)
                st.session_state.analysis_result = ImpactAnalysisResult(
                    **parsed_data
                )
              else:
                completion = openrouter_client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.2,
                    max_tokens=2048,
                )
                st.session_state.qa_result = (
                    completion.choices[0].message.content
                )

              st.session_state.used_model = f"{model_name} (OpenRouter)"
              status_container.success(f"Valmis! (Malli: `{model_name}`)")
              time.sleep(1)
              success = True
              st.rerun()
              break
            except Exception as m_err:
              st.sidebar.warning(
                  f"OpenRouter malli {model_name} epäonnistui: {m_err}"
              )
              continue

        except Exception as e:
          status_container.error(f"Virhe OpenRouter API-kutsussa: {e}")

    # --- GOOGLE GEMINI ---
    elif ai_provider == "Google Gemini":
      try:
        client = genai.Client(api_key=GEMINI_API_KEY)
        model_variants = [
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            "gemini-1.5-flash",
        ]

        for model_name in model_variants:
          try:
            if app_mode == "Muutosvaikutusanalyysi":
              config = types.GenerateContentConfig(
                  system_instruction=system_instruction,
                  response_mime_type="application/json",
                  response_schema=ImpactAnalysisResult,
                  temperature=0.2,
              )
            else:
              config = types.GenerateContentConfig(
                  system_instruction=system_instruction,
                  temperature=0.2,
              )

            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )

            if app_mode == "Muutosvaikutusanalyysi":
              st.session_state.analysis_result = response.parsed
            else:
              st.session_state.qa_result = response.text

            st.session_state.used_model = model_name
            status_container.success(f"Valmis! (Malli: `{model_name}`)")
            time.sleep(1)
            success = True
            st.rerun()
            break
          except Exception as e:
            st.sidebar.warning(f"Gemini {model_name} virhe: {e}")
            continue
      except Exception as e:
        status_container.error(f"Gemini client -virhe: {e}")

    # --- GROQ ---
    elif ai_provider == "Groq (Llama 3)":
      if OpenAI is None:
        status_container.error("OpenAI-kirjastoa ei ole asennettu.")
      else:
        try:
          groq_client = OpenAI(
              api_key=GROQ_API_KEY,
              base_url="[https://api.groq.com/openai/v1](https://api.groq.com/openai/v1)",
              timeout=20.0,
          )

          groq_model = "llama3-70b-8192"

          if app_mode == "Muutosvaikutusanalyysi":
            schema_json_str = json.dumps(
                ImpactAnalysisResult.model_json_schema(), ensure_ascii=False
            )
            groq_prompt = (
                f"{prompt}\n\nVastaa täsmälleen seuraavan JSON-skeeman"
                f" mukaan:\n```json\n{schema_json_str}\n```"
            )

            completion = groq_client.chat.completions.create(
                model=groq_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": groq_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=2048,
            )

            raw_content = completion.choices[0].message.content.strip()
            if raw_content.startswith("```"):
              raw_content = (
                  raw_content.replace("```json", "").replace("```", "").strip()
              )

            parsed_data = json.loads(raw_content)
            st.session_state.analysis_result = ImpactAnalysisResult(
                **parsed_data
            )
          else:
            completion = groq_client.chat.completions.create(
                model=groq_model,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
                max_tokens=2048,
            )
            st.session_state.qa_result = completion.choices[0].message.content

          st.session_state.used_model = f"{groq_model} (Groq)"
          status_container.success(f"Valmis! (Malli: `{groq_model}`)")
          time.sleep(1)
          success = True
          st.rerun()
        except Exception as e:
          status_container.error(f"Virhe Groq API-kutsussa: {e}")

    # --- OPENAI ---
    elif ai_provider == "OpenAI ChatGPT":
      if OpenAI is None:
        status_container.error("OpenAI-kirjastoa ei ole asennettu.")
      else:
        try:
          openai_client = OpenAI(api_key=OPENAI_API_KEY, timeout=20.0)

          if app_mode == "Muutosvaikutusanalyysi":
            completion = openai_client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                response_format=ImpactAnalysisResult,
                temperature=0.2,
            )
            st.session_state.analysis_result = (
                completion.choices[0].message.parsed
            )
          else:
            completion = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
            st.session_state.qa_result = completion.choices[0].message.content

          st.session_state.used_model = "gpt-4o"
          status_container.success("Valmis! (Malli: `gpt-4o`)")
          time.sleep(1)
          success = True
          st.rerun()
        except Exception as e:
          status_container.error(f"Virhe OpenAI API-kutsussa: {e}")

# ==============================================================================
# 7. TULOSTEN ESITTÄMINEN
# ==============================================================================

# A) YLEISEN KYSYMYKSEN (QA) TULOKSET
if app_mode == "Kysy arkkitehtuurista (QA)" and st.session_state.qa_result:
  used_model_name = st.session_state.get("used_model", "tuntematon-malli")
  st.markdown("---")
  st.header("Vastaus kysymykseen")
  st.caption(f"Vastauksen tuottanut malli: `{used_model_name}`")
  st.markdown(st.session_state.qa_result)

# B) MUUTOSVAIKUTUSANALYYSI-TILAN TULOKSET
elif (
    app_mode == "Muutosvaikutusanalyysi"
    and st.session_state.analysis_result is not None
):
  res: ImpactAnalysisResult = st.session_state.analysis_result
  used_model_name = st.session_state.get("used_model", "tuntematon-malli")

  st.markdown("---")
  st.header("Analyysin tulokset")

  col1, col2, col3 = st.columns(3)
  col1.metric("Kokonaisriskitaso", res.overall_risk)
  col2.metric(
      "Vaikutuksen alaiset järjestelmät",
      f"{res.affected_systems_count} / {len(MVA_DATA['systems'])} kpl",
  )
  col3.metric("Käytetty malli", used_model_name)

  if res.overall_risk == "KORKEA":
    st.error(f"**Yhteenveto:** {res.summary}")
  elif res.overall_risk == "KOHTALAINEN":
    st.warning(f"**Yhteenveto:** {res.summary}")
  else:
    st.success(f"**Yhteenveto:** {res.summary}")

  with st.expander("Strateginen linjaus ja tavoitteiden arviointi", expanded=True):
    st.write(res.strategic_alignment)

  col_left, col_right = st.columns([1, 1])

  with col_left:
    st.subheader("Vaikutuskartta (Riippuvuudet)")
    try:
      st.graphviz_chart(res.dot_graph)
    except Exception:
      st.info("Riippuvuuskaavion renderöinti epäonnistui. Raakakoodi:")
      st.code(res.dot_graph)

  with col_right:
    st.subheader("Vaikutukset järjestelmittäin & Omistajat")
    for sys_imp in res.impacts:
      owner_name = "Ei määritetty"
      for s in MVA_DATA["systems"]:
        if s["id"] == sys_imp.system_id:
          owner_name = s.get("owner", "Ei määritetty")
          break

      with st.expander(
          f"**{sys_imp.system_name}** ({sys_imp.impact_type}) - Omistaja:"
          f" {owner_name} | Riski: {sys_imp.risk_level}"
      ):
        st.write(f"**Järjestelmä-ID:** `{sys_imp.system_id}`")
        st.write(f"**Vastuuhenkilö / Omistaja:** {owner_name}")
        st.write(f"**Riskitaso:** {sys_imp.risk_level}")
        st.write(f"**Kuvaus:** {sys_imp.description}")

  st.subheader("Suositellut toimenpiteet")
  for rec in res.recommendations:
    st.markdown(f"- {rec}")

  # ==========================================================================
  # 8. EVALUOINTIOSIO (SUPABASE - VAIN MUUTOSVAIKUTUSANALYYSI-TILASSA)
  # ==========================================================================
  st.markdown("---")
  st.subheader("Asiantuntijan evaluointi (Opinnäytetyön aineistonkeruu)")
  st.caption(
      "Arvioi tekoälyn tekemän muutosvaikutusanalyysin laatua ja luotettavuutta."
  )

  with st.form("eval_form"):
    eval_rating = st.radio(
        "Osuiko tekoälyn arviointitulos ja riskitaso oikeaan?",
        [
            "Täysin oikein (5/5)",
            "Osittain oikein (3/5)",
            "Virheellinen/Puutteellinen (1/5)",
        ],
        horizontal=True,
    )
    eval_comments = st.text_area(
        "Asiantuntijan kommentit, havaitut puutteet tai hallusinaatiot:"
    )
    submit_eval = st.form_submit_button("Tallenna evaluointipalaute")

    if submit_eval:
      conn = None
      cursor = None
      try:
        db_url = st.secrets.get(
            "SUPABASE_DB_URL", os.environ.get("SUPABASE_DB_URL", "")
        )
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()

        cursor.execute(
            """
                    INSERT INTO evaluations (timestamp, model, scenario, proposal, ai_overall_risk, eval_rating, eval_comments)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
            (
                datetime.now().isoformat(),
                used_model_name,
                scenario_choice,
                user_input,
                res.overall_risk,
                eval_rating,
                eval_comments,
            ),
        )

        conn.commit()
        st.success(
            "Palaute tallennettu turvallisesti Supabase-pilvitietokantaan!"
        )
      except Exception as e:
        if conn:
          conn.rollback()
        st.error(f"Virhe tietokantaan tallennuksessa: {e}")
      finally:
        if cursor:
          cursor.close()
        if conn:
          conn.close()
