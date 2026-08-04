#!/usr/bin/env python3
"""
Demo 2: Probar la API de Kimi K2 directamente (sin TokioAI)
Requiere: pip install openai
API Key: https://platform.moonshot.cn/
Kimi K2 usa formato OpenAI-compatible (misma libreria!)
"""
import os
import sys

# Cargar API key del entorno o pedirla
api_key = os.getenv("KIMI_API_KEY") or os.getenv("MOONSHOT_API_KEY")
if not api_key:
    api_key = input("Pega tu Kimi API Key (sk-...): ").strip()
    if not api_key:
        print("ERROR: Necesitas una API key. Ve a https://platform.moonshot.cn/")
        sys.exit(1)

from openai import OpenAI

# Crear cliente -- MISMA libreria que OpenAI pero con distinta URL
client = OpenAI(
    api_key=api_key,
    base_url="https://api.moonshot.cn/v1"
)

# Generar texto
print("\n--- Enviando pregunta a Kimi K2 ---\n")
response = client.chat.completions.create(
    model="kimi-k2-0711-preview",
    messages=[
        {"role": "system", "content": "Eres un profesor de tecnologia. Responde en espanol."},
        {"role": "user", "content": "Explicame que es una API REST en 3 lineas, como si fuera un alumno de secundaria."}
    ],
    max_tokens=500,
)

print(response.choices[0].message.content)
print("\n--- Tokens usados ---")
if response.usage:
    print(f"  Input:  {response.usage.prompt_tokens} tokens")
    print(f"  Output: {response.usage.completion_tokens} tokens")
    print(f"  Total:  {response.usage.total_tokens} tokens")
