#!/usr/bin/env python3
"""
Demo 1: Probar la API de Gemini directamente (sin TokioAI)
Requiere: pip install google-genai
API Key: https://aistudio.google.com/apikey
"""
import os
import sys

# Cargar API key del entorno o pedirla
api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    api_key = input("Pega tu Gemini API Key (AIza...): ").strip()
    if not api_key:
        print("ERROR: Necesitas una API key. Ve a https://aistudio.google.com/apikey")
        sys.exit(1)

from google import genai

# Crear cliente
client = genai.Client(api_key=api_key)

# Generar texto
print("\n--- Enviando pregunta a Gemini 2.5 Flash ---\n")
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Explicame que es una API REST en 3 lineas, como si fuera un alumno de secundaria."
)

print(response.text)
print("\n--- Tokens usados ---")
if hasattr(response, 'usage_metadata'):
    um = response.usage_metadata
    print(f"  Input:  {um.prompt_token_count} tokens")
    print(f"  Output: {um.candidates_token_count} tokens")
    print(f"  Total:  {um.total_token_count} tokens")
