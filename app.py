# app.py
import streamlit as st
import psycopg2
from datetime import datetime
from styles import load_custom_css

# Ladataan mukautetut tyylit
load_custom_css()

st.title("Minimum Viable Architecture - Arviointi")
st.write("Arvioi alla olevaa muutosvaikutusanalyysiä ja ehdotusta.")

# Esimerkkilomake / kentät (mukauta tarpeen mukaan omiin muuttujiisi)
used_model_name = "GPT-4o"
scenario_choice = "Skenaario 1: Pilvisiirtymä"
change_proposal = "Päivitetään rajapintojen rakenteet mikroarkkitehtuuriksi."
res = type('Obj', (object,), {'overall_risk': 'Keskitaso'})()

with st.form("eval_form"):
    st.subheader("Arviointilomake")
    eval_rating = st.selectbox("Arvosana (1-5)", ["1", "2", "3", "4", "5"])
    eval_comments = st.text_area("Kommentit ja perustelut")
    
    submit_eval = st.form_submit_button("Tallenna palaute")

if submit_eval:
    try:
        # Haetaan tietokannan osoite Streamlit Secretsistä
        db_url = st.secrets["SUPABASE_DB_URL"]
        
        # Avataan yhteys Supabaseen
        conn = psycopg2.connect(db_url)
        cursor = conn.cursor()
        
        # Tallennetaan tiedot Supabase-tietokantaan
        cursor.execute("""
            INSERT INTO evaluations (timestamp, model, scenario, proposal, ai_overall_risk, eval_rating, eval_comments)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            datetime.now().isoformat(),
            used_model_name,
            scenario_choice,
            change_proposal,
            res.overall_risk,
            eval_rating,
            eval_comments
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        st.success("Palaute tallennettu turvallisesti tietokantaan!")
    except Exception as e:
        st.error(f"Virhe tietokantaan tallennuksessa: {e}")
