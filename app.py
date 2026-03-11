import streamlit as st
import requests
import pandas as pd
import os
import re
from groq import Groq
from dotenv import load_dotenv

# 1. CONFIGURACIÓN DEL SISTEMA
st.set_page_config(page_title="Hevy Coach AI", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

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

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json: return pd.DataFrame(), pd.DataFrame()
    lista_r, lista_e = [], []
    for rutina in datos_json["workouts"]:
        f_c = rutina.get("start_time", "")
        vol_r = 0
        for ej in rutina.get("exercises", []):
            nombre_ej = ej.get("title")
            for s in ej.get("sets", []):
                p, r = s.get("weight_kg") or 0, s.get("reps") or 0
                vol_r += (p * r)
                rm = p * (1 + (r / 30)) if r > 0 else 0
                lista_e.append({
                    "Fecha Cruda": f_c, "Ejercicio": nombre_ej, 
                    "Peso (Kg)": p, "Reps": r, "1RM Est.": round(rm, 1)
                })
        lista_r.append({"Fecha Cruda": f_c, "Rutina": rutina.get("title"), "Volumen": vol_r})
    df_r, df_e = pd.DataFrame(lista_r), pd.DataFrame(lista_e)
    for df in [df_r, df_e]:
        if not df.empty:
            f_dt = pd.to_datetime(df["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA)
            df["Fecha"] = f_dt.dt.strftime('%d/%m/%Y')
            df["Fecha_Sort"] = f_dt
    return df_r, df_e

# 3. INTERFAZ
if not API_KEY:
    st.error("⚠️ Configura HEVY_API_KEY.")
else:
    datos_crudos = obtener_datos_hevy_auto()
    if datos_crudos:
        df_r, df_e = procesar_datos(datos_crudos)
        sem_auto = detectar_semana_actual(datos_crudos)
        
        st.title("⚡ Hevy Coach AI")

        # --- SELECTORES GLOBALES (Para que la IA sea dinámica) ---
        col_1, col_2 = st.columns([1, 1])
        with col_1:
            semana_sel = st.slider("Fase del Ciclo:", 1, 8, value=sem_auto, key="global_sem")
        with col_2:
            ejercicio_sel = st.selectbox("Ejercicio Actual:", df_e["Ejercicio"].unique(), key="global_ej")

        # --- REGLAS LÓGICAS ---
        reglas = {
            1: ("Calibración", "NO llegues al fallo. Peso base."),
            2: ("Sobrecarga", "Sube peso o haz +1 repetición."),
            3: ("Fuerza Pura", "Peso máximo para 10-12 reps."),
            4: ("Tortura Mecánica", "MISMO PESO Sem 3. Pausa 2 seg abajo."),
            5: ("Reinicio", "Pesos de Semana 2. Técnica limpia."),
            6: ("Nuevo Pico", "Superar récord de Semana 3."),
            7: ("Prueba Final", "Pesos récord con bajada de 4s."),
            8: ("Descarga", "Baja todo al 50%. 1 serie menos.")
        }
        fase, desc = reglas[semana_sel]
        p_max = df_e[df_e["Ejercicio"] == ejercicio_sel]["Peso (Kg)"].max()

        # --- COACH IA AUTOMÁTICO (Siempre visible) ---
        st.markdown(f"### 🧠 Coach: {ejercicio_sel}")
        if client:
            # Función de cache para no gastar API de más en cada refresh visual
            @st.cache_data(ttl=60) # Cache de 1 min para el consejo
            def analizar_con_ia(sem, fas, reg, ej, maximo):
                try:
                    prompt = f"Coach, Pablo (estudiante sistemas, 21 años) está en Semana {sem} ({fas}). Regla: {reg}. Ejercicio: {ej}. Récord: {maximo}kg. Meta: Definición extrema. Consejo táctico corto en español paraguayo."
                    chat = client.chat.completions.create(
                        messages=[{"role": "user", "content": prompt}],
                        model="llama-3.3-70b-versatile",
                        temperature=0.7
                    )
                    return chat.choices[0].message.content
                except: return "Coach analizando..."
            
            st.info(analizar_con_ia(semana_sel, fase, desc, ejercicio_sel, p_max))
        
        st.write("---")

        # --- TABS DE DATOS ---
        t1, t2, t3 = st.tabs(["📊 Rendimiento", "📈 Tabla Fuerza", "💧 Agua"])
        
        with t1:
            st.subheader("Volumen por Sesión")
            df_plot = df_r.sort_values("Fecha_Sort").tail(10)
            st.line_chart(df_plot.set_index("Fecha")["Volumen"])
            
            # Alertas automáticas
            rutinas_rec = df_r.head(8)
            for tipo in ["Push", "Pull", "Torso", "Leg"]:
                f = rutinas_rec[rutinas_rec["Rutina"].str.contains(tipo, case=False, na=False)]
                if len(f) >= 2:
                    v_act, v_ant = f.iloc[0]["Volumen"], f.iloc[1]["Volumen"]
                    if v_act < v_ant: st.error(f"🚨 **{tipo.upper()}**: Volumen bajó.")
                    else: st.success(f"✅ **{tipo.upper()}**: Estímulo sólido.")

        with t2:
            st.subheader("Historial estilo Excel")
            df_hist = df_e[df_e["Ejercicio"] == ejercicio_sel].sort_values("Fecha_Sort", ascending=False)
            st.dataframe(df_hist[["Fecha", "Peso (Kg)", "Reps", "1RM Est."]], use_container_width=True, hide_index=True)

        with t3:
            st.subheader("💧 Protocolo de Hidratación Completo")
            st.checkbox("04:30 AM - Sal + Café", key="h1")
            st.checkbox("05:00 AM - 500ml Gym", key="h2")
            st.checkbox("08:00 AM - 12PM - 500ml Oficina", key="h3")
            st.checkbox("12:00 PM - Almuerzo (250ml) + Caminata", key="h4")
            st.checkbox("13:30 PM - Tereré (Máximo 1L)", key="h5")
            st.checkbox("17:00 PM - Cardio Intenso (500ml)", key="h6")
            st.checkbox("19:00 PM - Universidad (500ml)", key="h7")
            st.checkbox("22:00 PM - Shutdown Líquidos", key="h8")
