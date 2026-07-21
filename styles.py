# styles.py
import streamlit as st

def load_custom_css():
    st.markdown("""
        <style>
            /* Piilotetaan vain Streamlitin brändäykset, ei kosketa yläpalkin rakenteisiin */
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}

            /* Mukautettu tyyli sivupalkille */
            [data-testid="stSidebar"] {
                background-color: #111827;
                border-right: 1px solid #1f2937;
            }

            /* Korttien / expanderien tyylittely */
            .streamlit-expanderHeader {
                background-color: #1e293b;
                border-radius: 8px;
                border: 1px solid #334155;
            }

            /* Metriikkalaatikoiden visuaalinen parannus */
            [data-testid="stMetric"] {
                background-color: #1e293b;
                padding: 15px;
                border-radius: 8px;
                border: 1px solid #334155;
            }
        </style>
    """, unsafe_allow_html=True)
