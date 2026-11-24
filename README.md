# daily-brief

Scripts en Python que devuelven en JSON, ya limpios, los datos de un resumen diario:

- **Blackboard**: eventos de hoy y de mañana del feed iCal (clases, entregas y exámenes), con las horas en Europe/Madrid.
- **Clima de Madrid**: previsión del día desde [Open-Meteo](https://open-meteo.com/), con [met.no](https://api.met.no/) como proveedor alternativo. Ninguno necesita API key.

Si una de las dos fuentes falla, el programa no se rompe: su bloque sale como `null`, el error se anota en `errores` y el código de salida es 0.

## Instalación

Necesitas Python 3.11 o superior.

```bash
pip install -r requirements.txt        # para ejecutarlo
pip install -r requirements-dev.txt    # para los tests
```

## Uso

```bash
export BLACKBOARD_ICS_URL='...'        # URL de tu feed iCal (secreta)
python -m brief                        # hoy (fecha de Europe/Madrid)
python -m brief --date 2026-11-24
pytest -q                              # sin conexión a internet
```

`--date AAAA-MM-DD` hace que el script trabaje como si ese día fuera hoy: saca los eventos de Blackboard de esa fecha y de la siguiente, y el clima de esa fecha. Sin `--date` usa la fecha actual de Madrid, no la del ordenador. Open-Meteo y met.no solo tienen previsión para los próximos días, así que con fechas pasadas o muy lejanas el clima sale como `null`, con su error en `errores`.

## Clima: proveedores y `clima_fuente`

1. **Open-Meteo**. Si responde 429 (límite de peticiones) o 5xx, el script reintenta hasta 3 veces, esperando 2, 4 y 8 s.
2. **met.no** (`locationforecast 2.0`, Instituto Meteorológico de Noruega) se usa si Open-Meteo sigue fallando por cualquier motivo. Sus horas vienen en UTC y se pasan a hora de Madrid. Como met.no casi nunca da la probabilidad de lluvia fuera de los países nórdicos, el script la estima: una hora con más de 0,1 mm de lluvia prevista cuenta como lluvia.

Las dos peticiones llevan el User-Agent `daily-brief/1.0 github.com/fabiialon/daily-brief`, que met.no exige.

El campo de primer nivel `clima_fuente` indica de dónde salió el clima: `"open-meteo"`, `"met.no"` o `null` si fallaron los dos. En ese último caso el error de ambos queda en `errores`.

## Variables de entorno

| Variable | Qué es |
|---|---|
| `BLACKBOARD_ICS_URL` | URL del feed iCal de Blackboard. Es un secreto: no la guardes en el repo (`.env` está en `.gitignore`). Si falta, sale un error de la fuente `blackboard`. |

## Ejemplo de salida (datos inventados)

```json
{
  "fecha": "2026-11-24",
  "manana": "2026-11-25",
  "blackboard": {
    "hoy": [
      {
        "asignatura": "MANAGEMENT TOOLS & PRINCIPLES",
        "sesion": 26,
        "inicio": "2026-11-24T10:30:00+01:00",
        "fin": "2026-11-24T11:50:00+01:00",
        "aula": "Z-02.03",
        "tipo": "clase_presencial"
      },
      {
        "asignatura": "Group Homework",
        "sesion": null,
        "inicio": "2026-11-24T23:59:00+01:00",
        "fin": "2026-11-24T23:59:00+01:00",
        "aula": null,
        "tipo": "entrega"
      }
    ],
    "manana": [],
    "hay_management_hoy": true
  },
  "clima": {
    "max": 9,
    "min": 6,
    "prob_lluvia_max": 90,
    "tramos_lluvia": ["13–17 h"],
    "descripcion": "☁️ nublado",
    "paraguas": true,
    "linea": "🌡️ 6–9 °C · nublado, lluvia 13–17 h ☔ (llévate paraguas)"
  },
  "clima_fuente": "open-meteo",
  "errores": []
}
```

Tipos de evento: `examen`, `entrega`, `clase_presencial`, `clase_asincrona` y `otro`.

## Tarea programada y modo prueba

`ROUTINE_PROMPT.md` contiene el prompt de la tarea programada que usa este script.

La tarea también se puede lanzar a mano para probarla (sección 11 del prompt):

- Si el texto con el que se lanza contiene "PRUEBA" y una fecha (p. ej. `PRUEBA 2026-11-25`), esa fecha hace de "hoy". Se usa para Blackboard (`python -m brief --date AAAA-MM-DD`), Google Calendar, cumpleaños, recordatorios 🔔 y la regla de JP Morgan.
- El mensaje y la notificación empiezan por "🧪 PRUEBA".
- Los emails son siempre los de las últimas 24 h reales, y el mensaje lo indica.
- Al final del mensaje se añade "🔧 Diagnóstico:": si funcionaron git clone, pip y el JSON, qué fuentes tuvieron que usar el método alternativo y de dónde salió el clima.
- "PRUEBA" sin fecha usa la fecha real de hoy y aplica todo lo anterior.
