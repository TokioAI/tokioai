#!/usr/bin/env python3
"""
Demo 3: Como funciona una Tool (Function Calling) -- explicacion paso a paso

Las Tools permiten que un modelo de AI ejecute funciones en tu computadora.
El modelo NO ejecuta codigo -- solo DECIDE que funcion llamar y con que parametros.
Tu codigo es el que ejecuta la funcion y devuelve el resultado al modelo.

Flujo:
1. Usuario pregunta algo
2. Modelo decide: "necesito llamar la tool get_weather con city=Tokyo"
3. Tu codigo ejecuta get_weather("Tokyo") y obtiene el resultado
4. Le devuelves el resultado al modelo
5. El modelo genera la respuesta final con esa informacion
"""
import os
import sys
import json
import subprocess

# --- Definir una Tool ---

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Obtener el clima actual de una ciudad",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "Nombre de la ciudad (ej: 'Buenos Aires', 'Tokyo')"
                    }
                },
                "required": ["city"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Ejecutar un comando en la terminal y devolver la salida",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Comando bash a ejecutar"
                    }
                },
                "required": ["command"]
            }
        }
    }
]


# --- Implementar las Tools ---

def get_weather(city: str) -> str:
    """Consultar el clima usando wttr.in (gratis, sin API key)"""
    try:
        result = subprocess.run(
            ["curl", "-s", f"wttr.in/{city}?format=%C+%t+%h+%w"],
            capture_output=True, text=True, timeout=10
        )
        return f"Clima en {city}: {result.stdout.strip()}"
    except Exception as e:
        return f"Error consultando clima: {e}"


def run_command(command: str) -> str:
    """Ejecutar un comando en la terminal"""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=15
        )
        output = (result.stdout + result.stderr).strip()
        return output[:2000] if output else "(sin salida)"
    except Exception as e:
        return f"Error: {e}"


def execute_tool(name: str, args: dict) -> str:
    """Router de tools -- ejecuta la funcion correcta"""
    if name == "get_weather":
        return get_weather(args["city"])
    elif name == "run_command":
        return run_command(args["command"])
    else:
        return f"Tool desconocida: {name}"


# --- Demo con Gemini ---

def demo_with_gemini():
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY no configurada. Saltando demo Gemini.")
        return

    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    # Convertir tools al formato Gemini
    fn_decls = []
    for tool in TOOLS:
        fn = tool["function"]
        fn_decls.append(types.FunctionDeclaration(
            name=fn["name"],
            description=fn["description"],
            parameters=fn["parameters"],
        ))

    gemini_tools = [types.Tool(function_declarations=fn_decls)]

    print("\n" + "="*60)
    print("  DEMO: Tools con Gemini 2.5 Flash")
    print("="*60)

    # Pregunta que requiere usar tools
    user_msg = "Cual es el clima en Buenos Aires? Y de paso dime cuanto espacio libre tengo en disco."
    print(f"\nUsuario: {user_msg}\n")

    contents = [types.Content(role="user", parts=[types.Part(text=user_msg)])]

    # Primera llamada -- el modelo decidira usar tools
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(tools=gemini_tools),
    )

    # Procesar la respuesta
    for candidate in response.candidates:
        for part in candidate.content.parts:
            if part.function_call:
                fc = part.function_call
                print(f"  [TOOL CALL] {fc.name}({dict(fc.args)})")

                # Ejecutar la tool
                result = execute_tool(fc.name, dict(fc.args))
                print(f"  [RESULT]    {result}")

                # Devolver resultado al modelo
                contents.append(candidate.content)
                contents.append(types.Content(
                    role="user",
                    parts=[types.Part(function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    ))]
                ))

    # Segunda llamada -- el modelo genera la respuesta final con los resultados
    response2 = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
        config=types.GenerateContentConfig(tools=gemini_tools),
    )

    print(f"\nGemini: {response2.text}")


# --- Demo con Kimi K2 ---

def demo_with_kimi():
    api_key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
    if not api_key:
        print("\nKIMI_API_KEY no configurada. Saltando demo Kimi.")
        return

    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url="https://api.moonshot.cn/v1")

    print("\n" + "="*60)
    print("  DEMO: Tools con Kimi K2")
    print("="*60)

    user_msg = "Que clima hace en Tokyo? Y ejecuta 'uname -a' para ver el sistema operativo."
    print(f"\nUsuario: {user_msg}\n")

    messages = [
        {"role": "system", "content": "Eres un asistente. Responde en espanol."},
        {"role": "user", "content": user_msg},
    ]

    # Primera llamada
    response = client.chat.completions.create(
        model="kimi-k2-0711-preview",
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
    )

    msg = response.choices[0].message

    if msg.tool_calls:
        messages.append(msg)  # agregar respuesta del modelo

        for tc in msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"  [TOOL CALL] {fn_name}({fn_args})")

            result = execute_tool(fn_name, fn_args)
            print(f"  [RESULT]    {result}")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

        # Segunda llamada con resultados
        response2 = client.chat.completions.create(
            model="kimi-k2-0711-preview",
            messages=messages,
            tools=TOOLS,
        )

        print(f"\nKimi K2: {response2.choices[0].message.content}")
    else:
        print(f"\nKimi K2: {msg.content}")


# --- Main ---

if __name__ == "__main__":
    print("="*60)
    print("  DEMO: Function Calling / Tools")
    print("  El modelo decide QUE herramienta usar.")
    print("  Tu codigo EJECUTA la herramienta.")
    print("  El modelo genera la respuesta con el resultado.")
    print("="*60)

    demo_with_gemini()
    demo_with_kimi()

    print("\n" + "="*60)
    print("  FIN DE LA DEMO")
    print("="*60)
