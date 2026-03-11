import streamlit as st
import requests
import pandas as pd
import os
import re
import google.generativeai as genai
from dotenv import load_dotenv

# 1. CONFIGURACIÓN
st.set_page_config(page_title="Hevy Coach AI", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

# 2. FUNCIONES DE DATOS
@st.cache_data(ttl=300) 
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    todos_los_workouts = []
    for pagina in range(1, 4): 
        params = {"page": pagina, "pageSize": 10} 
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            datos_p = response.json()
            if "workouts" in datos_p: todos_los_workouts.extend(datos_p["workouts"])
    return {"workouts": todos_los_workouts} if todos_los_workouts else None

def detectar_semana_actual(datos_json):
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0: return 1
    for ej in datos_json["workouts"][0].get("exercises", []):
        match = re.search(r'[Ss]emana\s*(\d+)', ej.get("notes", ""))
        if match: return int(match.group(1))
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json: return pd.DataFrame(), pd.DataFrame()
    lista_r, lista_e = [], []
    # Diccionario para traducir meses a español en el eje X
    meses_es = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun", 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}
    
    for rutina in datos_json["workouts"]:
        vol_rutina = 0
        f_c = rutina.get("start_time", "")
        for ej in rutina.get("exercises", []):
            for s in ej.get("sets", []):
                p, r = s.get("weight_kg") or 0, s.get("reps") or 0
                vol_rutina += (p * r)
                rm = p * (1 + (r / 30)) if r > 0 else 0
                lista_e.append({
                    "Fecha Cruda": f_c, "Ejercicio": ej.get("title"), "Peso": p, "1RM": round(rm, 1)
                })
        lista_r.append({"Fecha Cruda": f_c, "Rutina": rutina.get("title"), "Volumen": vol_rutina})
    
    df_r, df_e = pd.DataFrame(lista_r), pd.DataFrame(lista_e)
    for df in [df_r, df_e]:
        if not df.empty:
            f_ajustada = pd.to_datetime(df["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA)
            # Formato en español: Día mes (Ej: 11 Mar)
            df["Fecha Visual"] = f_ajustada.apply(lambda x: f"{x.day} {meses_es[x.month]}")
            df["Fecha Orden"] = f_ajustada
    return df_r, df_e

# 3. INTERFAZ
if not API_KEY:
    st.error("⚠️ Configura la HEVY_API_KEY.")
else:
    with st.spinner("Sincronizando..."):
        crudo = obtener_datos_hevy_auto()
    if crudo:
        df_r, df_e = procesar_datos(crudo)
        sem_auto = detectar_semana_actual(crudo)
        
        st.title("⚡ Hevy Coach AI")
        t1, t2, t3, t4 = st.tabs(["📊 Historial", "📈 Fuerza", "🧠 Coach", "💧 Agua"])
        
        with t1:
            st.subheader("Volumen Total")
            # Ordenamos para que el gráfico fluya de izquierda a derecha
            df_plot_r = df_r.sort_values("Fecha Orden").tail(10)
            st.line_chart(df_plot_r.set_index("Fecha Visual")["Volumen"])

        with t2:
            st.subheader("Progreso de Fuerza")
            ej_sel = st.selectbox("Elegir Ejercicio:", df_e["Ejercicio"].unique())
            df_f = df_e[(df_e["Ejercicio"] == ej_sel) & (df_e["Peso"] > 0)].sort_values("Fecha Orden")
            if not df_f.empty:
                df_f_g = df_f.groupby("Fecha Visual")["1RM"].max()
                st.line_chart(df_f_g)
            else:
                st.info("Sin datos de peso para este ejercicio.")

        with t3:
            st.subheader("Análisis del Coach")
            sem = st.slider("Semana actual:", 1, 8, value=sem_auto)
            # Reglas del manual [cite: 1, 14, 15, 36]
            reglas = {
                1: "Calibración (Tempo 3-1, RIR 2) [cite: 16, 19]",
                2: "Sobrecarga (Tempo 3-1, +Peso o +Reps) [cite: 21, 24, 25]",
                3: "Fuerza Pura (Tempo Normal, RIR 1) [cite: 26, 28, 30]",
                4: "Tortura (Tempo 4-2, MISMO PESO Sem 3) [cite: 31, 33, 34]",
                5: "Reinicio (Tempo 3-1, Pesos Sem 2) [cite: 37, 39, 40]",
                6: "Nuevo Pico (Tempo Normal, Récord Sem 3) [cite: 41, 43, 44]",
                7: "Prueba Final (Tempo 4-2, Pesos Sem 6) [cite: 45, 47, 48]",
                8: "Descarga (50% de peso, -1 serie) [cite: 50, 53, 54]"
            }
            st.info(f"📅 **Fase:** {reglas[sem]}")
            
            ej_c = st.selectbox("Analizar ejercicio:", df_e["Ejercicio"].unique(), key="c")
            df_c = df_e[df_e["Ejercicio"] == ej_c]
            p_max = df_c["Peso"].max() if not df_c.empty else 0
            
            if st.button("🧠 Consultar Coach", use_container_width=True):
                if not GEMINI_API_KEY: st.error("Falta GEMINI_API_KEY")
                else:
                    with st.spinner("Pensando..."):
                        try:
                            # Cambio de modelo a la versión estable para evitar el 404
                            model = genai.GenerativeModel('gemini-1.5-flash-latest')
                            prompt = f"Instrucción: Escribe en ESPAÑOL. Eres un coach de gimnasio. Tu cliente Pablo está en Semana {sem}. Regla: {reglas[sem]}. Ejercicio: {ej_c}. Su máximo es {p_max}kg. Dale un consejo corto y motivador de cómo entrenar hoy para no perder músculo en definición."
                            res = model.generate_content(prompt)
                            st.write(res.text)
                        except Exception as e: st.error(f"Error: {e}")

        with t4:
            # Protocolo de hidratación [cite: 75]
            st.subheader("💧 Hidratación")
            st.checkbox("04:30 AM - Sal + Café ", key="h1")
            st.checkbox("05:00 AM - 500ml Gym [cite: 79, 80]", key="h2")
            st.checkbox("13:30 PM - Tereré (Límite 1L) [cite: 91, 93]", key="h3")
            st.checkbox("22:00 PM - Shutdown Líquidos [cite: 104, 105]", key="h4")
