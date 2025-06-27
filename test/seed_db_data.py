#!/usr/bin/env python3
import os
import json
import datetime
import psycopg2
import random
import datetime

# Cadena de conexión: ajusta host/puerto/usuario/password si es necesario
DSN = os.getenv("DB_DSN", "postgresql://postgres:changeme@localhost:5433/olt")
conn = psycopg2.connect(DSN)
cur = conn.cursor()

# 0) Asegurarnos de que la OLT 'zyxel' exista
cur.execute("""
  INSERT INTO olt(id, vendor, host, port, poll_interval)
  VALUES (%s, %s, %s, %s, %s)
  ON CONFLICT (id) DO NOTHING
""", (
  "zyxel",      # id de la OLT (debe coincidir con ont.olt_id)
  "zyxel",      # vendor (huawei o zyxel)
  "127.0.0.1",  # host (ajusta si es necesario)
  22,           # port
  300           # poll_interval en segundos
))
conn.commit()

# 1) Creamos varias ONTs de prueba
insert_ont = """
  INSERT INTO ont(olt_id, vendor_ont_id, serial, model, description, status, props)
  VALUES (%s, %s, %s,  %s, %s,  %s, %s)
  ON CONFLICT (olt_id, vendor_ont_id) DO NOTHING
  RETURNING id
"""
ids = []
for i in range(1, 6):
    props = json.dumps(
        {
            "AID": f"ont-1-{i}",
            "Status": "IS",
            "Template-ID": "Template-1-121",
            "FW Version": "V544ACHK1b1_20",
            "Distance": f"{i} m",
         }
    )
    cur.execute(insert_ont,
                ("zyxel", f"ont-1-{i}", f"5A5958458CADA65{i}", "PX3321-T1", "ont-test", 1, props))
    ret = cur.fetchone()
    ids.append(ret[0] if ret else None)

# 2) Insertar lecturas de potencia históricas
insert_power = """
  INSERT INTO ont_power(time, ont_id, ptx, prx, status)
  VALUES (%s, %s, %s, %s, %s)
"""
now = datetime.datetime.utcnow()
for ont_id in filter(None, ids):
    for h in range(0, 24, 6):
        t = now - datetime.timedelta(hours=h)
        # status = random.randint(0, 1)
        status = 1
        if status:
            # valor aleatorio de ptx entre 2 y 5
            ptx = random.uniform(2.0, 5.0)
            # valor aleatorio de prx entre -24 y -17
            prx = random.uniform(-24.0, -17.0)
            cur.execute(insert_power, (t, ont_id, ptx, prx, status))
        else:
            cur.execute(insert_power, (t, ont_id, None, None, status))


conn.commit()
cur.close()
conn.close()

print("Datos de prueba insertados en BBDD directamente.")
