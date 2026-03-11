import streamlit as st
import requests
import pandas as pd
import os
import re
from groq import Groq
from dotenv import load_dotenv

# 1. CONFIGURACIÓN
st.set_page_config(page_title="Hevy AI Coach", page_icon="⚡", layout="centered")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None

# 2. MOTOR DE DATOS
@st.cache_data(ttl=300) 
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    todos = []
    for p in range(1, 4): 
        res = requests.get(url, headers=headers, params={"page": p, "pageSize": 10})
        if res.status_code == 200:
            datos = res.json()
            if "workouts" in datos: todos.extend(datos["workouts"])
    return {"workouts": todos} if todos else None

def detectar_semana_actual(datos_json):
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0: return 1
    for ej in datos_json["workouts"][0].get("exercises", []):
        match = re.search(r'[Ss]emana\s*(\d+)', ej.get("notes", ""))
        if match: return int(match.group(1))
    return 1

# Función para que la IA analice automáticamente
def obtener_consejo_auto(semana, fase, regla, ejercicio, maximo):
    if not client: return "Configura la GROQ_API_KEY para activar el Coach."
    try:
        prompt = f"""
        Eres un Coach de Élite. Usuario: Pablo (21 años, estudiante de sistemas).
        Meta: Definición extrema reteniendo músculo.
        Contexto Actual: Semana {semana} ({fase}).
        Regla de hoy: {regla}.
        Ejercicio: {ejercicio}. Máximo histórico: {maximo}kg.
        Instrucción: Dame un consejo táctico y corto (máximo 60 palabras) para aplicar HOY en el gimnasio.
        Habla en español paraguayo/latino, directo al grano.
        """
        chat = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b-versatile",
            temperature=0.7
        )
        return chat.choices[0].message.content
    except:
        return "El Coach está descansando. Intenta de nuevo en un minuto."

# 3. INTERFAZ
datos_crudos = obtener_datos_hevy_auto()
if datos_crudos:
    # Procesamiento básico
    lista_e = []
    for r in datos_crudos["workouts"]:
        f_c = r.get("start_time", "")
        for ej in r.get("exercises", []):
            for s in ej.get("sets", []):
                p = s.get("weight_kg") or 0
                reps = s.get("reps") or 0
                rm = p * (1 + (reps / 30)) if reps > 0 else 0
                lista_e.append({"Fecha": f_c, "Ejercicio": ej.get("title"), "Peso": p, "1RM": round(rm, 1)})
    df_e = pd.DataFrame(lista_e)
    sem_auto = detectar_semana_actual(datos_crudos)

    # UI PRINCIPAL
    st.title("⚡ Hevy AI Coach")
    
    # --- CABECERA DE CONTROL ---
    col_a, col_b = st.columns([1, 1])
    with col_a:
        semana = st.selectbox("Semana Ciclo:", range(1, 9), index=sem_auto-1)
    with col_b:
        ejercicio = st.selectbox("Ejercicio:", df_e["Ejercicio"].unique())

    # --- REGLAS LÓGICAS ---
    reglas = {
        1: ("Calibración", "NO llegues al fallo. Busca sensaciones."),
        2: ("Sobrecarga", "Sube 2.5kg o haz +1 repetición."),
        3: ("Fuerza Pura", "Peso máximo para 10-12 reps."),
        4: ("Tortura Mecánica", "Mismo peso Sem 3. Pausa 2 seg abajo."),
        5: ("Reinicio", "Pesos de Semana 2. Técnica perfecta."),
        6: ("Nuevo Pico", "Superar récord de Semana 3."),
        7: ("Prueba Final", "Pesos récord con bajada de 4s."),
        8: ("Descarga", "Baja todo al 50%. 1 serie menos.")
    }
    fase, desc = reglas[semana]
    p_max = df_e[df_e["Ejercicio"] == ejercicio]["Peso"].max()

    # --- EL CEREBRO IA (AUTOMÁTICO) ---
    st.markdown(f"### 🧠 Coach: {ejercicio}")
    with st.container():
        st.info(obtener_consejo_auto(semana, fase, desc, ejercicio, p_max))

    st.write("---")

    # --- TABS DE APOYO ---
    t1, t2, t3 = st.tabs(["📊 Historial de Pesos", "💧 Hidratación", "🎯 Reglas Fase"])
    
    with t1:
        df_hist = df_e[df_e["Ejercicio"] == ejercicio].sort_values("Fecha", ascending=False)
        st.dataframe(df_hist[["Fecha", "Peso", "1RM"]].head(10), use_container_width=True, hide_index=True)

    with t2:
        st.subheader("💧 Protocolo Diario")
        st.checkbox("04:30 AM - Sal + Café", key="h1")
        st.checkbox("13:30 PM - Tereré (Límite 1L)", key="h2")
        st.checkbox("22:00 PM - Shutdown Líquidos", key="h3")

    with t3:
        st.write(f"**Fase Actual:** {fase}")
        st.write(f"**Instrucción:** {desc}")
