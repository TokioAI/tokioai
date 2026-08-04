# TokioAI -- Demo Completa para Alumnos
## Crear APIs + Integrar Gemini y Kimi K2 + Crear Tools

Fecha: 2026-08-01
Instructor: @mrmoz

---

## PARTE 1: Crear las API Keys (desde cero)

### 1A. Crear API Key de Google Gemini (GRATIS)

1. Ir a: https://aistudio.google.com/apikey
2. Login con cuenta de Google
3. Click "Create API Key"
4. Seleccionar un proyecto de GCP (o crear uno nuevo)
5. Copiar la API key (empieza con `AIza...`)
6. GUARDARLA en un lugar seguro -- no compartir

Modelos disponibles (gratis con limites):
- gemini-2.5-flash     (rapido, barato, bueno para todo)
- gemini-2.5-pro       (mas potente, limites mas bajos)

### 1B. Crear API Key de Kimi K2 (Moonshot AI)

1. Ir a: https://platform.moonshot.cn/
2. Registrarse (se puede con email)
3. Ir a "API Keys" en el dashboard
4. Crear nueva API key
5. Copiar la key (empieza con `sk-...`)

Modelo: kimi-k2-0711-preview (el ultimo, state-of-the-art)
Base URL: https://api.moonshot.cn/v1

ALTERNATIVA -- usar Kimi K2 via OpenRouter:
1. Ir a: https://openrouter.ai/
2. Registrarse
3. Ir a Keys -> Create Key
4. Copiar la key
5. Modelo: moonshotai/kimi-k2

---

## PARTE 2: Instalar TokioAI CLI

### 2A. Clonar el repo

```bash
git clone https://github.com/TokioAI/tokioai.git
cd tokioai
```

### 2B. Crear entorno virtual Python

```bash
# Crear entorno virtual
python3 -m venv .venv

# Activar
source .venv/bin/activate      # Linux/Mac
# .venv\Scripts\activate       # Windows

# Verificar
which python3
python3 --version   # debe ser 3.10+
```

### 2C. Instalar dependencias

```bash
# Instalar TokioAI con soporte para TODOS los providers
pip install -e ".[all]"

# Esto instala:
#   - anthropic (Claude)
#   - openai (OpenAI, OpenRouter, Ollama, Kimi K2)
#   - google-genai (Gemini)
#   - paramiko (SSH)
```

### 2D. Configurar con el Setup Wizard

```bash
tokioai --setup
```

Esto abre un wizard interactivo que te pregunta el provider y credenciales.

PERO para esta demo, vamos a configurar MANUALMENTE para tener
multiples providers a la vez.

---

## PARTE 3: Configurar Multiples Providers

### 3A. Crear archivo de configuracion

```bash
mkdir -p ~/.tokioai
nano ~/.tokioai/.env
```

Contenido:

```bash
# === GEMINI (Google AI Studio) ===
GEMINI_API_KEY=AIzaSy...TU_KEY_AQUI

# === KIMI K2 (Moonshot AI - OpenAI compatible) ===
KIMI_API_KEY=sk-...TU_KEY_AQUI
KIMI_BASE_URL=https://api.moonshot.cn/v1

# === Provider por defecto ===
TOKIOAI_PROVIDER=gemini
TOKIOAI_MODEL=flash
```

### 3B. Verificar que funciona

```bash
# Probar Gemini
tokio -m flash "di hola en 3 idiomas"

# Probar Kimi K2
tokio -m kimi "di hola en 3 idiomas"
```

---

## PARTE 4: Probar APIs directamente (sin TokioAI)

### 4A. Probar Gemini con Python puro

```python
#!/usr/bin/env python3
"""test_gemini.py -- Probar la API de Gemini directamente"""
from google import genai

# Crear cliente con API key
client = genai.Client(api_key="AIzaSy...TU_KEY")

# Generar texto
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Explicame que es una API en 3 lineas"
)

print(response.text)
```

```bash
python3 test_gemini.py
```

### 4B. Probar Kimi K2 con Python puro

```python
#!/usr/bin/env python3
"""test_kimi.py -- Probar la API de Kimi K2 directamente"""
from openai import OpenAI

# Kimi K2 usa formato OpenAI-compatible
client = OpenAI(
    api_key="sk-...TU_KEY",
    base_url="https://api.moonshot.cn/v1"
)

response = client.chat.completions.create(
    model="kimi-k2-0711-preview",
    messages=[
        {"role": "user", "content": "Explicame que es una API en 3 lineas"}
    ]
)

print(response.choices[0].message.content)
```

```bash
python3 test_kimi.py
```

---

## PARTE 5: Integracion en TokioAI (ya hecha)

TokioAI ya soporta Kimi K2 como provider nativo. El sistema detecta
automaticamente el provider segun las variables de entorno.

### Como funciona internamente:

```
Usuario escribe: tokio -m kimi "hola"
                      |
                      v
           resolve_model("kimi")
           -> "kimi-k2-0711-preview"
                      |
                      v
           detect_provider() para ese modelo
           -> "kimi" (porque tiene "kimi" en el nombre)
                      |
                      v
           init_client("kimi")
           -> OpenAI(base_url="https://api.moonshot.cn/v1", api_key=KIMI_API_KEY)
           -> client_type = "openai" (usa protocolo OpenAI-compatible)
                      |
                      v
           _chat_openai_stream() con tools
           -> El modelo puede ejecutar herramientas en tu terminal
```

### Cambiar modelo en tiempo real:

```
$ tokio

tokio> hola que tal  (usa el modelo por defecto)

tokio> model kimi    (cambia a Kimi K2)
-> Switched to kimi-k2-0711-preview

tokio> ahora estas usando Kimi K2

tokio> model flash   (cambia a Gemini Flash)
-> Switched to gemini-2.5-flash

tokio> models        (ver todos los disponibles)
```

---

## PARTE 6: Crear una Tool nueva

### Que es una Tool?

Una Tool es una funcion que el AI puede llamar. Por ejemplo:
- execute_local: ejecutar un comando en la terminal
- read_file: leer un archivo
- search_files: buscar texto en archivos

Vamos a crear una Tool nueva: `weather` -- consultar el clima.

### 6A. Agregar la Tool al archivo ops.py

Buscar la lista TOOLS en `tokioai_cli/ops.py` y agregar:

```python
# Agregar al final de la lista TOOLS:
{
    "name": "get_weather",
    "description": "Get current weather for a city. Returns temperature, conditions, humidity.",
    "input_schema": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name (e.g., 'Buenos Aires', 'Tokyo', 'New York')",
            },
        },
        "required": ["city"],
    },
},
```

### 6B. Implementar la ejecucion en execute_tool()

Buscar la funcion `execute_tool` en ops.py y agregar:

```python
elif name == "get_weather":
    city = input_data["city"]
    # Usar wttr.in -- servicio gratuito sin API key
    result = _run_cmd(f'curl -s "wttr.in/{city}?format=j1" | python3 -c "import sys,json; d=json.load(sys.stdin); c=d[\"current_condition\"][0]; print(f\"City: {city}\\nTemp: {c[\"temp_C\"]}C / {c[\"temp_F\"]}F\\nCondition: {c[\"weatherDesc\"][0][\"value\"]}\\nHumidity: {c[\"humidity\"]}%\\nWind: {c[\"windspeedKmph\"]} km/h\")"')
    return result
```

### 6C. Probar la Tool

```bash
tokio "cual es el clima en Buenos Aires?"
```

El AI detectara que puede usar `get_weather` y la llamara automaticamente:

```
tokio> cual es el clima en Buenos Aires?

  [tool] get_weather(city="Buenos Aires")
  City: Buenos Aires
  Temp: 12C / 54F
  Condition: Partly cloudy
  Humidity: 65%
  Wind: 15 km/h

  Ahora mismo en Buenos Aires esta parcialmente nublado con 12 grados...
```

---

## PARTE 7: Tool avanzada -- Escaner de puertos

```python
# Tool definition (agregar a TOOLS):
{
    "name": "port_scan",
    "description": "Scan open ports on a target host. Only for authorized targets.",
    "input_schema": {
        "type": "object",
        "properties": {
            "host": {"type": "string", "description": "Target IP or hostname"},
            "ports": {"type": "string", "description": "Port range (e.g., '1-1000', '22,80,443')"},
        },
        "required": ["host"],
    },
},

# Ejecucion (agregar a execute_tool):
elif name == "port_scan":
    host = input_data["host"]
    ports = input_data.get("ports", "22,80,443,8080,3306,5432")
    return _run_cmd(f'python3 -c "import socket; [print(f\"Port {{p}}: OPEN\") for p in [{ports}] if socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect_ex((\"{host}\", p)) == 0]"', timeout=15)
```

---

## PARTE 8: Arquitectura completa

```
                    +------------------+
                    |   Usuario        |
                    |   (terminal)     |
                    +--------+---------+
                             |
                    +--------v---------+
                    |  TokioAI CLI     |
                    |  interactive.py  |
                    +--------+---------+
                             |
                    +--------v---------+
                    |   TokioAI Ops    |
                    |   ops.py         |
                    |                  |
                    |  +-- Provider ---+-------+--------+
                    |  |   Router     |       |        |
                    +--+--+-----------+--+----+---+----+
                       |               |          |
              +--------v---+   +-------v--+  +---v--------+
              | Gemini API |   | Kimi K2  |  | Claude API |
              | (Google)   |   | (Moon)   |  | (Anthropic)|
              +------------+   +----------+  +------------+

    Cada provider convierte al formato que su API necesita.
    Gemini usa google-genai SDK.
    Kimi K2 usa OpenAI-compatible SDK.
    Claude usa Anthropic SDK.
    OpenRouter/Ollama usan OpenAI SDK con base_url distinta.
```

---

## PARTE 9: Resumen de comandos

```bash
# Instalar
git clone https://github.com/TokioAI/tokioai.git && cd tokioai
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"

# Configurar
tokioai --setup                     # wizard interactivo
# o manualmente: nano ~/.tokioai/.env

# Usar
tokio                               # modo interactivo
tokio "tu pregunta"                 # una sola pregunta
tokio -m kimi "pregunta"            # usar Kimi K2
tokio -m flash "pregunta"           # usar Gemini Flash
tokio -m sonnet "pregunta"          # usar Claude Sonnet

# Dentro del CLI
model kimi                          # cambiar a Kimi K2
model flash                         # cambiar a Gemini
models                              # ver todos
/status                             # estado del sistema
memory                              # ver memoria persistente
tasks                               # ver tareas activas
reset                               # limpiar conversacion
exit                                # salir
```

---

## NOTAS IMPORTANTES

1. Las API keys NUNCA se comparten ni se suben a git
2. El archivo ~/.tokioai/.env esta en .gitignore
3. Gemini tiene tier gratuito generoso (bueno para empezar)
4. Kimi K2 requiere creditos (verificar pricing en platform.moonshot.cn)
5. Las Tools se ejecutan EN TU MAQUINA -- cuidado con lo que permites
6. TokioAI enmascara credenciales automaticamente en la salida
