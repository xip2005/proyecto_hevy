import streamlit as st
import requests
import pandas as pd
import os
import re
from dotenv import load_dotenv

# 1. CONFIGURACIÓN MOBILE-FIRST (Centrado y sin sidebar abierto por defecto)
st.set_page_config(page_title="Hevy Coach", page_icon="⚡", layout="centered", initial_sidebar_state="collapsed")

load_dotenv()
API_KEY = os.getenv("HEVY_API_KEY")
ZONA_HORARIA = os.getenv("TIMEZONE", "America/Asuncion") 

# 2. FUNCIONES DE DATOS (Auto-Sincronización Inteligente)
@st.cache_data(ttl=300) # Memoria de 5 minutos para volar en el celular
def obtener_datos_hevy_auto():
    url = "https://api.hevyapp.com/v1/workouts"
    headers = {"api-key": API_KEY, "Accept": "application/json"}
    todos_los_workouts = []
    
    for pagina in range(1, 4): 
        params = {"page": pagina, "pageSize": 10} 
        response = requests.get(url, headers=headers, params=params)
        
        if response.status_code == 200:
            datos_pagina = response.json()
            if "workouts" in datos_pagina:
                todos_los_workouts.extend(datos_pagina["workouts"])
        else:
            return None 
            
    if todos_los_workouts:
        return {"workouts": todos_los_workouts}
    return None

def detectar_semana_actual(datos_json):
    if not datos_json or "workouts" not in datos_json or len(datos_json["workouts"]) == 0:
        return 1
    ultimo_entreno = datos_json["workouts"][0]
    for ej in ultimo_entreno.get("exercises", []):
        notas = ej.get("notes", "")
        match = re.search(r'[Ss]emana\s*(\d+)', notas)
        if match:
            semana = int(match.group(1))
            return semana if 1 <= semana <= 8 else 1
    return 1

def procesar_datos(datos_json):
    if not datos_json or "workouts" not in datos_json:
        return pd.DataFrame(), pd.DataFrame()
    
    lista_rutinas = []
    lista_ejercicios = []
    
    for rutina in datos_json["workouts"]:
        nombre_rutina = rutina.get("title", "Sin nombre")
        fecha_cruda = rutina.get("start_time", "")
        volumen_total = 0
        
        for ejercicio in rutina.get("exercises", []):
            nombre_ej = ejercicio.get("title", "Desconocido")
            for serie in ejercicio.get("sets", []):
                peso = serie.get("weight_kg") or 0
                reps = serie.get("reps") or 0
                volumen_total += (peso * reps)
                rm_estimado = peso * (1 + (reps / 30)) if reps > 0 else 0
                
                lista_ejercicios.append({
                    "Fecha Cruda": fecha_cruda,
                    "Rutina": nombre_rutina,
                    "Ejercicio": nombre_ej,
                    "Serie": serie.get("index", 0) + 1,
                    "Peso (Kg)": peso,
                    "Reps": reps,
                    "1RM Est.": round(rm_estimado, 1)
                })
                
        lista_rutinas.append({
            "Fecha Cruda": fecha_cruda,
            "Rutina": nombre_rutina,
            "Volumen Total (Kg)": volumen_total
        })
        
    df_rutinas = pd.DataFrame(lista_rutinas)
    df_ejercicios = pd.DataFrame(lista_ejercicios)
    
    for df in [df_rutinas, df_ejercicios]:
        if not df.empty:
            fechas_ajustadas = pd.to_datetime(df["Fecha Cruda"], utc=True).dt.tz_convert(ZONA_HORARIA) + pd.Timedelta(hours=1)
            df["Fecha"] = fechas_ajustadas.dt.strftime('%m-%d %H:%M') # Formato más corto para celular
            df["Fecha Solo"] = fechas_ajustadas.dt.strftime('%Y-%m-%d')
            
    return df_rutinas, df_ejercicios

# 3. INTERFAZ PRINCIPAL
if not API_KEY:
    st.error("⚠️ Falta API Key de Hevy.")
else:
    datos_crudos = obtener_datos_hevy_auto()
        
    if datos_crudos:
        df_rutinas, df_ejercicios = procesar_datos(datos_crudos)
        semana_auto = detectar_semana_actual(datos_crudos)
        
        if not df_rutinas.empty:
            st.title("⚡ Panel Deportivo")
            
            # KPIs en Columnas (En móvil se apilarán solas)
            col1, col2 = st.columns(2)
            with col1:
                rutina_max = df_rutinas.loc[df_rutinas['Volumen Total (Kg)'].idxmax()]
                st.metric("Récord de Volumen", f"{rutina_max['Volumen Total (Kg)']:,.0f} kg", f"Día {rutina_max['Rutina']}")
            with col2:
                st.metric("Foco Actual", "Definición", "Retención Muscular")

            st.write("---")

            # PESTAÑAS OPTIMIZADAS PARA NAVEGACIÓN TÁCTIL
            tab1, tab2, tab3, tab4 = st.tabs(["📊 Rendimiento", "📈 Fuerza 1RM", "⚙️ Coach 8 Semanas", "💧 Agua"])
            
            with tab1:
                st.subheader("Análisis Crítico")
                rutinas_recientes = df_rutinas.head(10) 
                
                for tipo_rutina in ["Push", "Pull", "Torso", "Leg"]:
                    datos_tipo = rutinas_recientes[rutinas_recientes["Rutina"].str.contains(tipo_rutina, case=False, na=False)]
                    if len(datos_tipo) >= 2:
                        vol_actual = datos_tipo.iloc[0]["Volumen Total (Kg)"]
                        vol_anterior = datos_tipo.iloc[1]["Volumen Total (Kg)"]
                        if vol_actual < vol_anterior:
                            st.error(f"🚨 **ALERTA {tipo_rutina.upper()}:** Volumen bajó a {vol_actual}kg. Forzar intensidad.")
                        else:
                            st.success(f"✅ **ÓPTIMO {tipo_rutina.upper()}:** Volumen en {vol_actual}kg.")
                            
                st.subheader("Tonelaje Histórico")
                st.line_chart(df_rutinas.iloc[::-1].set_index("Fecha")["Volumen Total (Kg)"], use_container_width=True)

            with tab2:
                st.subheader("Calculadora 1RM (Epley)")
                ejercicios_unicos = df_ejercicios["Ejercicio"].unique()
                ejercicio_elegido = st.selectbox("Ejercicio:", ejercicios_unicos, key="ejercicio_rm")
                
                df_filtro = df_ejercicios[df_ejercicios["Ejercicio"] == ejercicio_elegido]
                # FILTRO ANTI-CEROS: Solo calculamos si el peso es mayor a 0
                df_con_peso = df_filtro[df_filtro["Peso (Kg)"] > 0]
                
                if df_con_peso.empty:
                    st.info("💡 Este ejercicio no tiene registros de peso (Ej: peso corporal o bandas). No se puede calcular el 1RM.")
                else:
                    df_max_rm = df_con_peso.groupby("Fecha Solo")["1RM Est."].max().reset_index()
                    df_max_rm["Fecha Solo"] = pd.to_datetime(df_max_rm["Fecha Solo"])
                    
                    st.line_chart(df_max_rm.set_index("Fecha Solo"), y="1RM Est.", use_container_width=True)

            with tab3:
                st.subheader("Sistema de Hipertrofia")
                
                if "slider_semanas" not in st.session_state:
                    st.session_state.slider_semanas = semana_auto
                    
                semana = st.slider("Fase del ciclo:", 1, 8, key="slider_semanas")
                
                reglas_ciclo = {
                    1: {"fase": "Calibración", "tempo": "3-1", "rir": "2", "desc": "NO llegues al fallo."},
                    2: {"fase": "Sobrecarga Inicial", "tempo": "3-1", "rir": "1-2", "desc": "Sube peso o haz 2 reps extra."},
                    3: {"fase": "Fuerza Pura", "tempo": "Normal", "rir": "1", "desc": "Sube peso obligatorio (10-12 reps)."},
                    4: {"fase": "Tortura Mecánica", "tempo": "4-2", "rir": "Fallo", "desc": "MISMO PESO Sem 3. Pausa 2 seg."},
                    5: {"fase": "Reinicio Interno", "tempo": "3-1", "rir": "2", "desc": "Pesos de Semana 2. Técnica limpia."},
                    6: {"fase": "Nuevo Pico", "tempo": "Normal", "rir": "0", "desc": "Rompe récord de la Semana 3."},
                    7: {"fase": "Prueba Final", "tempo": "4-2", "rir": "Fallo", "desc": "Pesos récord con bajada de 4 seg."},
                    8: {"fase": "Descarga (Eco)", "tempo": "Normal", "rir": "Fácil", "desc": "Pesos al 50%. 1 serie menos."}
                }
                
                st.info(f"🎯 **{reglas_ciclo[semana]['fase']}**\n\n⏱️ Tempo: {reglas_ciclo[semana]['tempo']} | 🔋 RIR: {reglas_ciclo[semana]['rir']}\n\n📖 {reglas_ciclo[semana]['desc']}")
                
                ej_hipertrofia = st.selectbox("Proyectar peso para:", df_ejercicios["Ejercicio"].unique(), key="select_hiper")
                df_hist_ej = df_ejercicios[(df_ejercicios["Ejercicio"] == ej_hipertrofia) & (df_ejercicios["Peso (Kg)"] > 0)]
                
                if not df_hist_ej.empty:
                    peso_maximo = df_hist_ej["Peso (Kg)"].max()
                    peso_reciente = df_hist_ej.iloc[0]["Peso (Kg)"]
                    
                    if semana == 8:
                        st.success(f"⚖️ **Peso hoy:** {peso_maximo * 0.5:.1f} kg")
                    elif semana in [4, 7]:
                        st.warning(f"⚖️ **Peso hoy:** {peso_reciente} kg (Con Tempo {reglas_ciclo[semana]['tempo']})")
                    elif semana in [1, 5]:
                        st.info(f"⚖️ **Proyección:** Arrancas con tu récord de Semana 2 ({peso_maximo} kg).")
                    else:
                        st.info(f"📊 Récord histórico: **{peso_maximo} kg**.")
                else:
                    st.write("Sin registros de peso suficientes para este ejercicio.")

            with tab4:
                st.subheader("💧 Protocolo de Hidratación")
                st.write("Marca tu progreso del día:")
                st.checkbox("04:30 AM - Escudo Sal + Café", key="hidrato_1")
                st.checkbox("05:00 AM - Botella 500ml Gym", key="hidrato_2")
                st.checkbox("08:00 AM a 12PM - 500ml Oficina", key="hidrato_3")
                st.checkbox("12:00 PM - Almuerzo (250ml) + Caminata", key="hidrato_4")
                st.checkbox("13:30 PM - Tereré (Límite 1L)", key="hidrato_5")
                st.checkbox("17:00 PM - Cardio Intenso (500ml)", key="hidrato_6")
                st.checkbox("19:00 PM - Universidad (500ml)", key="hidrato_7")
                st.checkbox("22:00 PM - Shutdown (Cero líquidos)", key="hidrato_8")
                
        else:
            st.warning("Tu historial de Hevy está vacío.")