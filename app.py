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
    
    # Formateo de fechas para que sean legibles y ordenables
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
        t1, t2, t3, t4 = st.tabs(["📊 Rendimiento", "📈 Tabla Fuerza", "🧠 Coach Groq", "💧 Agua"])
        
        with t1:
            st.subheader("Volumen por Sesión")
            df_plot = df_r.sort_values("Fecha_Sort").tail(10)
            st.line_chart(df_plot.set_index("Fecha")["Volumen"])
            
            # Alertas automáticas
            st.write("---")
            rutinas_rec = df_r.head(8)
            for tipo in ["Push", "Pull", "Torso", "Leg"]:
                f = rutinas_rec[rutinas_rec["Rutina"].str.contains(tipo, case=False, na=False)]
                if len(f) >= 2:
                    v_act, v_ant = f.iloc[0]["Volumen"], f.iloc[1]["Volumen"]
                    if v_act < v_ant: st.error(f"🚨 **{tipo.upper()}**: Volumen cayó de {v_ant:,.0f} a {v_act:,.0f}kg.")
                    else: st.success(f"✅ **{tipo.upper()}**: Estímulo sólido en {v_act:,.0f}kg.")

        with t2:
            st.subheader("Historial de Pesos Reales")
            ej_sel = st.selectbox("Selecciona Ejercicio:", df_e["Ejercicio"].unique(), key="sel_f")
            
            # Filtramos y limpiamos la tabla para que sea "estilo Excel" pero moderna
            df_hist = df_e[df_e["Ejercicio"] == ej_sel].copy()
            df_hist = df_hist.sort_values("Fecha_Sort", ascending=False)
            
            # Mostramos solo las columnas que te importan en el gym
            tabla_limpia = df_hist[["Fecha", "Peso (Kg)", "Reps", "1RM Est."]]
            
            st.dataframe(tabla_limpia, use_container_width=True, hide_index=True)
            st.caption("💡 Ordenado del entrenamiento más reciente al más antiguo.")

        with t3:
            st.subheader("Sistema de Hipertrofia (8 Semanas)")
            sem = st.slider("Fase del Ciclo:", 1, 8, value=sem_auto, key="s_sem")
            
            reglas = {
                1: {"f": "Calibración", "t": "3-1", "d": "NO llegues al fallo. Peso base."},
                2: {"f": "Sobrecarga", "t": "3-1", "d": "Sube peso o haz +1 repetición."},
                3: {"f": "Fuerza Pura", "t": "Normal", "d": "Peso máximo para 10-12 reps."},
                4: {"f": "Tortura Mecánica", "t": "4-2", "d": "MISMO PESO Sem 3. Pausa 2 seg."},
                5: {"f": "Reinicio", "t": "3-1", "d": "Pesos de Semana 2. Técnica limpia."},
                6: {"f": "Nuevo Pico", "t": "Normal", "d": "Rompe récord de Semana 3."},
                7: {"f": "Prueba Final", "t": "4-2", "d": "Pesos récord con bajada de 4s."},
                8: {"f": "Descarga", "t": "Normal", "d": "Baja todo al 50%. 1 serie menos."}
            }
            st.info(f"🎯 **{reglas[sem]['f']}** | ⏱️ Tempo: {reglas[sem]['t']}\n\n📖 {reglas[sem]['d']}")
            
            ej_ai = st.selectbox("Analizar con IA:", df_e["Ejercicio"].unique(), key="s_ai")
            df_ai = df_e[df_e["Ejercicio"] == ej_ai]
            p_max = df_ai["Peso (Kg)"].max() if not df_ai.empty else 0
            
            if st.button("🧠 Consultar al Coach Groq", use_container_width=True):
                if client:
                    with st.spinner("Analizando..."):
                        try:
                            chat = client.chat.completions.create(
                                messages=[{"role": "user", "content": f"Coach, Pablo (estudiante sistemas, 21 años) está en Semana {sem} ({reglas[sem]['f']}). Regla: {reglas[sem]['d']}. Ejercicio: {ej_ai}. Récord: {p_max}kg. Meta: Definición extrema sin perder músculo. Dame un consejo táctico corto en español paraguayo."}],
                                model="llama-3.3-70b-versatile",
                            )
                            st.write(chat.choices[0].message.content)
                        except Exception as e: st.error(f"Error: {e}")

        with t4:
            st.subheader("💧 Protocolo de Hidratación")
            st.checkbox("04:30 AM - Sal + Café", key="h1")
            st.checkbox("05:00 AM - 500ml Gym", key="h2")
            st.checkbox("08:00 AM - 12PM - 500ml Oficina", key="h3")
            st.checkbox("13:30 PM - Tereré (Máximo 1L)", key="h4")
            st.checkbox("19:00 PM - Universidad (500ml)", key="h5")
            st.checkbox("22:00 PM - Shutdown Líquidos", key="h6")
