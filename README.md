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
python -m brief --doctor               # autodiagnóstico de cada fuente
pytest -q                              # sin conexión a internet
```

`--date AAAA-MM-DD` hace que el script trabaje como si ese día fuera hoy: saca los eventos de Blackboard de esa fecha y de la siguiente, y el clima de esa fecha. Sin `--date` usa la fecha actual de Madrid, no la del ordenador. Open-Meteo y met.no solo tienen previsión para los próximos días, así que con fechas pasadas o muy lejanas el clima sale como `null`, con su error en `errores`.

## Clima: proveedores y `clima_fuente`

1. **Open-Meteo**. Si hay un error de red o responde 429 (límite de peticiones) o 5xx, el script reintenta hasta 3 veces, esperando 2, 4 y 8 s. Blackboard y met.no se reintentan igual.
2. **met.no** (`locationforecast 2.0`, Instituto Meteorológico de Noruega) se usa si Open-Meteo sigue fallando por cualquier motivo. Sus horas vienen en UTC y se pasan a hora de Madrid. Como met.no casi nunca da la probabilidad de lluvia fuera de los países nórdicos, el script la estima: una hora con más de 0,1 mm de lluvia prevista cuenta como lluvia.

Las dos peticiones llevan el User-Agent `daily-brief/1.0 github.com/fabiialon/daily-brief`, que met.no exige.

El campo de primer nivel `clima_fuente` indica de dónde salió el clima: `"open-meteo"`, `"met.no"` o `null` si fallaron los dos. En ese último caso el error de ambos queda en `errores`.

## Autorreparación

Cada día a las 05:00 UTC (6:00 o 7:00 en Madrid, antes del resumen de las 7:55) se ejecuta el workflow `.github/workflows/health.yml`. También se puede lanzar a mano con `gh workflow run health.yml`. El workflow pasa `pytest` y `python -m brief --doctor`, que comprueba Blackboard, Open-Meteo y met.no por separado y da a cada fuente el estado `ok`, `reparado` o `fallo`, con la causa.

**Se arregla solo, sin que hagas nada:**
- Errores de red, 429 y 5xx: se reintentan con espera exponencial.
- Si `icalendar` no está instalado o falla, el calendario se lee con un parser de reserva escrito solo con la librería estándar. Blackboard sale como `reparado`.
- Si Open-Meteo falla, se usa met.no. Si fallan los dos, el clima sale `null` con la causa de cada uno.
- Si falla el código (tests rojos o un cambio de formato en una fuente, `formato_cambiado`), un segundo job lanza Claude Code (`anthropics/claude-code-action`). Claude diagnostica, corrige y ejecuta pytest y el doctor, con un máximo de 5 ciclos. Después el workflow vuelve a verificarlo y, si pytest y el doctor pasan, abre un PR y lo mergea a `main`. Claude solo puede editar archivos y ejecutar pytest y el doctor; no puede hacer commits ni leer el secreto del feed.

**Necesita tu intervención:**
- `enlace_caducado`: Blackboard responde 401/403/404 o una página de login. Hay que generar un enlace iCal nuevo, actualizar el secreto y la tarea programada.
- `dominio_bloqueado`: no se puede conectar con el servidor (proxy o conexión rechazada).
- `falta_configuracion`: falta el secreto `BLACKBOARD_ICS_URL`.
- Que Claude no consiga arreglar el código en 5 ciclos. Al día siguiente lo vuelve a intentar.

En esos casos se abre una única issue con la etiqueta `necesita-fabian` y los pasos exactos. Mientras siga el problema, cada día se añade un comentario a esa misma issue, y se cierra sola con el comentario "Resuelto" el primer día que todo sale bien.

Para ver las issues abiertas: `gh issue list --label necesita-fabian`, o la pestaña *Issues* del repo filtrada por esa etiqueta. Si un servicio está caído o limita las peticiones y no hay alternativa, el workflow sale en rojo pero no abre issue, porque no es algo que tú puedas arreglar.

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
