import streamlit as st
import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
from collections import deque

# --- PSY KROMETRISKA FUNKTIONER ---
def saturation_vapor_pressure(T):
    return 611.2 * np.exp((17.67 * T) / (T + 243.5))

def rh_to_absolute_moisture(T, RH):
    P_sat = saturation_vapor_pressure(T)
    P_v = (RH / 100.0) * P_sat
    return (P_v / (461.5 * (T + 273.15))) * 1000 

def absolute_moisture_to_rh(T, rho_v):
    P_sat = saturation_vapor_pressure(T)
    P_v = (rho_v / 1000.0) * 461.5 * (T + 273.15)
    return min(100.0, max(0.0, (P_v / P_sat) * 100))

# --- INDUSTRIAL REGULATOR CLASS ---
class IndustrialPID:
    def __init__(self, Xp, Ti, Td, dt, output_limits=(0, 100)):
        self.Xp = Xp 
        self.Ti = Ti 
        self.Td = Td 
        self.dt = dt
        self.min_limit, self.max_limit = output_limits
        self.integral = 0.0
        self.last_error = 0.0

    def calculate(self, setpoint, measurement):
        error = setpoint - measurement
        span = self.max_limit - self.min_limit
        Kp = span / self.Xp if self.Xp > 0 else 0.0
        
        if self.Ti > 0:
            self.integral += (error * self.dt) / (self.Ti * 60.0)
            self.integral = max(-span, min(span, self.integral))
        else:
            self.integral = 0.0
            
        derivative = ((error - self.last_error) / self.dt) * (self.Td * 60.0) if self.Td > 0 else 0.0
        output = Kp * (error + self.integral + derivative)
        self.last_error = error
        return max(self.min_limit, min(output, self.max_limit))

# --- STRÄMLIT GRÄNSSNITT ---
st.set_page_config(layout="wide", page_title="Klimatstyrning i Museum")
st.title("🏛️ Klimatstyrning i Museum")
st.markdown("Interaktivt simuleringsverktyg för studier av temperatur, fukt och sekvensreglering i en museisal under 24 timmar.")

# Sidomeny
st.sidebar.header("🎯 Börvärden (Setpoints)")
T_setpoint = st.sidebar.slider("Börvärde Temperatur (°C)", 18.0, 25.0, 21.0, 0.5)
RH_setpoint = st.sidebar.slider("Börvärde Fukt Start (RH %)", 30.0, 60.0, 45.0, 1.0)
RH_stop_limit = st.sidebar.slider("Befuktare Stopp-gräns (RH %)", 50.0, 75.0, 60.0, 1.0)

st.sidebar.header("🌤️ Utomhusklimat")
out_mode = st.sidebar.radio("Utetemperatur profil", ["Konstant", "Dygnsrytm (Dynamisk)"])
if out_mode == "Konstant":
    T_outdoor_const = st.sidebar.slider("Fast Utetemperatur (°C)", -10.0, 30.0, 10.0, 1.0)
    RH_outdoor_const = st.sidebar.slider("Fast Ute-fukt (RH %)", 20, 100, 70, 5)

st.sidebar.header("💨 Ventilationsflöde")
vent_mode = st.sidebar.radio("Luftflödesstyrning", ["Fast konstant flöde", "Behovsstyrt (Reglerat PID)"])
if vent_mode == "Fast konstant flöde":
    const_flow_h = st.sidebar.slider("Konstant luftomsättning (oms/h)", 0.2, 5.0, 1.0, 0.1)
else:
    st.sidebar.subheader("🎛️ Fläktreglering (Luftflöde PID)")
    flow_Xp = st.sidebar.slider("P-band Fläkt (Xp i °C)", 1.0, 10.0, 3.0, 0.5)
    flow_Ti = st.sidebar.slider("I-tid Fläkt (Ti i min)", 1.0, 30.0, 10.0, 1.0)
    flow_Td = st.sidebar.slider("D-tid Fläkt (Td i min)", 0.0, 5.0, 0.5, 0.1)

st.sidebar.header("♻️ Värmeåtervinnare (Roterande)")
max_eta_T = st.sidebar.slider("Max Temperaturverkningsgrad (%)", 0, 90, 80, 5) / 100.0
max_eta_x = st.sidebar.slider("Max Fuktverkningsgrad (%)", 0, 90, 70, 5) / 100.0

st.sidebar.header("⏱️ Systemdynamik")
dead_time_min = st.sidebar.slider("Dötid på tilluft (minuter)", 0, 15, 3, 1)

st.sidebar.header("🔥 Radiatorstyrning (Värme PI)")
rad_Xp = st.sidebar.slider("P-band Radiator (Xp i °C)", 0.5, 20.0, 5.0, 0.5)
rad_Ti = st.sidebar.slider("I-tid Radiator (Ti i min)", 1.0, 60.0, 20.0, 1.0)

st.sidebar.header("💨 Sekvensreglering Tilluft (LBA)")
ahu_Xp = st.sidebar.slider("P-band Sekvensregulator (Xp i °C)", 1.0, 30.0, 10.0, 1.0)
ahu_Ti = st.sidebar.slider("I-tid Sekvensregulator (Ti i min)", 1.0, 120.0, 30.0, 5.0)

# --- SIMULERINGSPARAMETRAR ---
dt = 60 
steg = int((24 * 3600) / dt)
Volym = 1000.0
U_total = 200.0
C_air = Volym * 1200.0
C_walls = C_air * 5.0

# Starttillstånd
T_room, T_structure = 20.0, 20.0
RH_initial = 50.0
g_rum = rh_to_absolute_moisture(T_room, RH_initial)
humidifier_on = False  

# Initiera regulatorer
pid_radiator = IndustrialPID(rad_Xp, rad_Ti, Td=0.0, dt=dt, output_limits=(0, 15000))

if vent_mode == "Behovsstyrt (Reglerat PID)":
    pid_flow = IndustrialPID(flow_Xp, flow_Ti, flow_Td, dt, output_limits=(0.5, 3.0))
else:
    pid_flow = None

pid_ahu_sequence = IndustrialPID(ahu_Xp, ahu_Ti, Td=0.0, dt=dt, output_limits=(-100.0, 200.0))

steps_delay = max(1, int((dead_time_min * 60) / dt))
delay_T_supply = deque([T_room] * steps_delay, maxlen=steps_delay)
delay_g_supply = deque([g_rum] * steps_delay, maxlen=steps_delay)

data_log = []

# --- SIMULERINGSLOOP ---
for s in range(steg):
    t_timmar = (s * dt) / 3600.0
    
    if out_mode == "Konstant":
        T_outdoor = T_outdoor_const
        RH_outdoor = RH_outdoor_const
    else:
        T_outdoor = 12.0 + 8.0 * np.sin(2 * np.pi * (t_timmar - 8) / 24)
        RH_outdoor = 70.0 - 20.0 * np.sin(2 * np.pi * (t_timmar - 8) / 24)
    g_outdoor = rh_to_absolute_moisture(T_outdoor, RH_outdoor)
    
    sol_vinst = 4000.0 * max(0.0, np.sin(2 * np.pi * (t_timmar - 6) / 24)) if 6 < t_timmar < 18 else 0.0
    personer = int(80 * np.sin(np.pi * (t_timmar - 10) / 8)) if 10.0 <= t_timmar <= 18.0 else 0
    int_varme_vinst = personer * 80.0
    int_fukt_vinst = personer * 50.0 / 3600

    if vent_mode == "Fast konstant flöde":
        flow_ach = const_flow_h
    else:
        flow_ach = pid_flow.calculate(22.0, T_room)
    flow = (flow_ach * Volym) / 3600

    RH_exhaust = absolute_moisture_to_rh(T_room, g_rum)
    if RH_exhaust <= RH_setpoint:
        humidifier_on = True
    elif RH_exhaust >= RH_stop_limit:
        humidifier_on = False

    # --- SEKVENSREGLERING TEMPERATUR ---
    seq_output = pid_ahu_sequence.calculate(T_setpoint, T_room)
    
    q_cooling = 0.0
    current_eta_T = 0.0
    current_eta_x = 0.0
    q_heating = 0.0
    
    if seq_output < 0:
        q_cooling = (abs(seq_output) / 100.0) * 10000.0 
    elif 0 <= seq_output <= 100:
        signal_ratio = seq_output / 100.0
        current_eta_T = signal_ratio * max_eta_T
        current_eta_x = signal_ratio * max_eta_x
    else:
        current_eta_T = max_eta_T
        current_eta_x = max_eta_x
        q_heating = ((seq_output - 100.0) / 100.0) * 12000.0 

    g_after_recovery = g_outdoor + current_eta_x * (g_rum - g_outdoor) if g_rum > g_outdoor else g_outdoor
    g_supply_calc = g_after_recovery + 4.5 if humidifier_on else g_after_recovery

    T_after_recovery = T_outdoor + current_eta_T * (T_room - T_outdoor) if T_room > T_outdoor else T_outdoor
    
    air_mass_flow = flow * 1.2
    if air_mass_flow > 0:
        T_supply_calc = T_after_recovery + (q_heating - q_cooling) / (air_mass_flow * 1000.0)
    else:
        T_supply_calc = T_outdoor
        
    T_supply_calc = max(15.0, min(28.0, T_supply_calc)) 
    rad_power = pid_radiator.calculate(T_setpoint, T_room)

    # Lägg till i dötids-köer
    delay_T_supply.append(T_supply_calc)
    delay_g_supply.append(g_supply_calc)
    
    # HÄR ÄR RÄTTELSEN: Plockar ut värdet [0] (äldsta värdet) ur dötidsköerna
    T_supply_actual = delay_T_supply[0]
    g_supply_actual = delay_g_supply[0]

    # Fysikaliska balanser
    q_trans = U_total * (T_room - T_outdoor)
    q_structure = 500.0 * (T_room - T_structure)
    q_vent = flow * 1.2 * 1000 * (T_supply_actual - T_room)
    
    T_room += ((rad_power + q_vent + int_varme_vinst + sol_vinst - q_trans - q_structure) * dt) / C_air
    T_structure += (q_structure * dt) / C_walls
    g_rum += (((flow * (g_supply_actual - g_rum)) + int_fukt_vinst) * dt) / Volym
    RH_room = absolute_moisture_to_rh(T_room, g_rum)

    data_log.append({
        'Tid': round(t_timmar, 2), 'T_inne': round(T_room, 2),
        'RH_inne': round(RH_room, 2), 'T_ute': round(T_outdoor, 2),
        'Besokare': personer, 'Sol': round(sol_vinst / 1000, 2),
        'Rad': round(rad_power / 1000, 2), 'T_tilluft': round(T_supply_actual, 2),
        'Rec': round((current_eta_T / (max_eta_T if max_eta_T > 0 else 1.0)) * 100 if max_eta_T > 0 else 0, 1), 
        'Varmare': round(q_heating / 1000, 2), 'Kylare': round(q_cooling / 1000, 2), 
        'Flow': round(flow_ach, 2)
    })

df = pd.DataFrame(data_log)

st.subheader("📥 Hämta simuleringsdata")
csv = df.to_csv(index=False, sep=';').encode('utf-8-sig')
st.download_button(label="Ladda ned (.CSV)", data=csv, file_name='museum_data.csv', mime='text/csv')

# --- GRAF-PLOTTNING ---
fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(12, 8))

# Graf 1: Temperatur
ax1.plot(df['Tid'], df['T_inne'], 'r-', label="Innetemp", linewidth=2)
ax1.axhline(T_setpoint, color='g', linestyle='--', label="Borvarde")
ax1.plot(df['Tid'], df['T_ute'], 'k--', alpha=0.4, label="Utetemp")
ax1.set_ylabel("Temperatur (°C)")
ax1.grid(True)
ax1.legend()

# Graf 2: Fukt
ax2.plot(df['Tid'], df['RH_inne'], 'b-', label="RH", linewidth=2)
ax2.axhline(RH_setpoint, color='g', linestyle=':', label="Start")
ax2.axhline(RH_stop_limit, color='r', linestyle=':', label="Stopp")
ax2.set_ylabel("Relativ fuktighet (%)")
ax2.set_ylim(20, 80)
ax2.grid(True)
ax2.legend()

# Graf 3: LBA Sekvenser
ax3.plot(df['Tid'], df['Rec'], 'orange', label="Atervinnare")
ax3.plot(df['Tid'], df['Varmare'], 'r-', label="Luftvarmare")
ax3.plot(df['Tid'], df['Kylare'], 'b-', label="Luftkylare")
ax3.set_ylabel("LBA Sekvenser Pådrag")
ax3.set_xlabel("Tid (h)")
ax3.grid(True)
ax3.legend()

# Graf 4: Rumsenheter
ax4.plot(df['Tid'], df['Rad'], 'brown', label="Radiator PI")
ax4.plot(df['Tid'], df['Flow'], 'c-', label="Flakt PID")
ax4.set_ylabel("Ställdon på rumssidan")
ax4.set_xlabel("Tid (h)")
ax4.grid(True)
ax4.legend()

st.pyplot(fig)
