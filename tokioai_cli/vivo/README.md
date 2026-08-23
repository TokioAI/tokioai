# TokioAI Vivo — Organismo Autónomo

Modo vivo del CLI de TokioAI: un agente autónomo, token-optimizado y seguro, que corre persistenemente vigilando el sistema, servicios, red, robots y más.

## Filosofía

- **95% reflejos locales gratis**: reglas simples manejan lo rutinario.
- **Cortex caro solo en anomalías**: Gear 2 (barato) cada pocos minutos; Gear 3 (caro) solo ante situaciones novedosas o críticas.
- **Token guard**: presupuesto por hora/sesión/día y límites de llamadas.
- **Memoria persistente**: world model comprimido, reglas aprendidas, métricas.
- **Seguridad graduada**: simulación → asistida → confiada → full, con kill switch y whitelist.

## Comandos

```bash
# Ver estado
tokio --vivo-status

# Modo simulación (por defecto seguro)
tokio --vivo --objective "mantener servidor saludable" --autonomy 0

# Asistido: avisa antes de destructivas (dry-run=False requiere --no-dry-run)
tokio --vivo --objective "mantener servidor saludable" --autonomy 1 --no-dry-run

# Confianza: ejecuta whitelist
tokio --vivo --objective "patrullar habitación con el robot" --autonomy 2 --no-dry-run

# Parar
tokio --vivo-stop
# o crear archivo STOP:
touch ~/.tokioai/vivo/STOP
```

## Opciones

- `--objective TEXT`: misión de alto nivel.
- `--autonomy {0,1,2,3}`: simulación, asistida, confiada, full.
- `--dry-run` / `--no-dry-run`: simular o ejecutar.
- `--budget-hour USD`: presupuesto horario (default 0.50).
- `--budget-session USD`: presupuesto de sesión (default 10.0).
- `--gear2-model MODEL`: modelo barato (default `meta-llama/llama-3.1-8b-instruct`).
- `--gear3-model MODEL`: modelo caro (default `moonshotai/kimi-k3`).
- `--tick S`: intervalo de sense/act loop (default 2s).
- `--cortex-interval S`: intervalo de revisión Gear 2 (default 300s).
- `--report-every S`: intervalo de reporte CLI (default 60s).

## Arquitectura

```
tokioai_cli/vivo/
├── config.py          # Configuración y rutas
├── token_guard.py     # Presupuesto y costos
├── safety.py          # Whitelist, kill switch, rate limits
├── world_memory.py    # Memoria persistente del mundo
├── watchdogs.py       # Sensores locales 0 tokens
├── brainstem.py       # Reflejos y reglas
├── cortex.py          # Razonamiento Gear 2/3
├── llm_client.py      # Cliente LLM (OpenRouter/TokioOps fallback)
├── action_executor.py # Ejecutor con whitelist y simulación
├── scheduler.py       # Tareas periódicas
├── vivo_loop.py       # Loop principal
├── cli_plugin.py      # Integración con `tokio`
└── templates/dashboard.html  # Dashboard estático opcional
```

## Datos

Todo se persiste en `~/.tokioai/vivo/`:

- `config.yaml`: configuración.
- `memory.json`: objects, events, health, rules.
- `token_guard.json`: gasto de tokens.
- `actions.log`: acciones ejecutadas (JSONL).
- `metrics.jsonl`: métricas periódicas.

## Costos estimados

- Gear 2 con `meta-llama/llama-3.1-8b-instruct` en OpenRouter: ~$0.00005 por llamada.
- Gear 3 con `moonshotai/kimi-k3`: ~$0.005-0.02 por llamada.
- Un modo vivo saludable revisando cada 5 min puede costar centavos por día.

## Seguridad

Nunca corre destructivas sin consentimiento según el nivel de autonomía. En nivel 2 (confiado) solo ejecuta comandos en `destructive_whitelist`. En nivel 3 todo está permitido. Usa `--dry-run` primero.
