# TokioAI Vivo v4.0 -- Guia Avanzada Completa

## Tabla de Contenidos

1. [Que es Vivo](#que-es-vivo)
2. [Arquitectura Interna](#arquitectura-interna)
3. [Modos de Uso](#modos-de-uso)
4. [Git-Safe Coding (NUEVO v4.0)](#git-safe-coding)
5. [Comandos CLI Completos](#comandos-cli)
6. [Configuracion Avanzada](#configuracion-avanzada)
7. [Objetivos: Como Escribirlos](#objetivos)
8. [Modelos y Proveedores](#modelos)
9. [Seguridad y Autonomia](#seguridad)
10. [Project Memory](#project-memory)
11. [Stuck Detection y Recovery](#stuck-detection)
12. [Vault (Secrets)](#vault)
13. [Monitoring y Debugging](#monitoring)
14. [Workflows Reales](#workflows)
15. [Limitaciones Actuales](#limitaciones)
16. [Roadmap](#roadmap)

---

## 1. Que es Vivo <a name="que-es-vivo"></a>

Vivo es el **modo autonomo** de TokioAI. Cuando lo activas, el agente queda corriendo
de forma persistente -- leyendo archivos, ejecutando comandos, escribiendo codigo,
commiteando a git, corriendo tests, y tomando decisiones. Es un ingeniero de software
autonomo con acceso completo a tu maquina.

**NO** es un servicio externo. Es un modo del CLI `tokio` que ya usas.

### Capacidades actuales:
- Lee y escribe archivos en cualquier directorio
- Ejecuta cualquier comando de shell
- Corre tests automaticamente (pytest, npm, cargo, go, make)
- Commitea a git con pipeline de seguridad completo (v4.0)
- Push a branches seguros, crea PRs
- Detecta cuando esta trabado y cambia de estrategia
- Memoria persistente que sobrevive context windows
- Vault encriptado para secrets/API keys
- Dual-model: modelo barato para rutina + modelo potente para razonamiento profundo
- Dashboard web para monitoreo

---

## 2. Arquitectura Interna <a name="arquitectura-interna"></a>

```
tokioai_cli/vivo/
  |-- cli_plugin.py      # Parseo de args, startup, daemon, follow, status
  |-- config.py          # VivoConfig dataclass + YAML persistence
  |-- vivo_loop.py       # Loop principal: cycle -> work_engine -> sleep -> repeat
  |-- work_engine.py     # El cerebro: LLM decide accion, engine la ejecuta
  |-- llm_client.py      # Wrapper para OpenRouter/Moonshot/etc
  |-- git_ops.py         # Git raw operations (init, commit, rollback, branch)
  |-- git_safe.py        # [v4.0] Safety layer: branch isolation, pre-commit, auto-rollback, PR
  |-- test_runner.py     # Corre tests (pytest/npm/cargo/go), parsea resultados
  |-- safety.py          # Autonomy levels, command blocking, rate limits
  |-- stuck_detector.py  # Detecta loops, sugiere escape strategies
  |-- project_memory.py  # Memoria persistente comprimida (facts, decisions, progress, todo)
  |-- token_guard.py     # Budget tracking ($/hr, $/session, calls/hr)
  |-- vault.py           # Secrets encriptados (AES-256)
  |-- watchdogs.py       # System watchdogs (CPU, disk, services)
  |-- vivo_output.py     # Output isolation (stderr + logfile, never stdout)
  |-- dashboard_server.py # WebSocket dashboard
  |-- tests/
      |-- test_vivo.py       # 36 unit tests
      |-- test_git_safe.py   # 20 unit tests para git safety
```

### Flow de un ciclo:

```
VivoLoop.run()
  -> work_engine.work_cycle()
     -> _build_context()           # Construye prompt con objetivo, historial, memoria
     -> llm_client.chat()          # LLM decide proxima accion (JSON)
     -> _parse_llm_json()          # Parsea respuesta robustamente
     -> _execute_action()          # Ejecuta la accion
        -> read_file / write_file / run_cmd / git_safe_commit / ...
     -> stuck_detector.record()    # Registra para deteccion de loops
     -> _save_work_log()           # Persiste estado
  -> sleep(tick_interval)
  -> repeat
```

### Gears (modelos):

- **Gear 2**: Modelo de rutina (barato, rapido). Ejemplo: kimi-k2.5, llama-8b, gpt-4o-mini
- **Gear 3**: Modelo de razonamiento profundo (caro, potente). Ejemplo: kimi-k3, claude-sonnet-4, gpt-4o
  - Se activa cuando el stuck detector detecta un loop
  - O cada 25 pasos como revision estrategica

---

## 3. Modos de Uso <a name="modos-de-uso"></a>

### 3.1 Modo Foreground (interactivo)
```bash
tokio --vivo --objective "Analizar el codebase de mi proyecto y generar un reporte de arquitectura" --autonomy 1
```
Vivo corre en tu terminal. Ves el output en tiempo real. Ctrl+C para parar.

### 3.2 Modo Background (daemon)
```bash
tokio --vivo --bg --objective "Refactorizar el modulo de auth" --autonomy 2 --hours 2
```
Se forkeara como daemon. Controlar con:
```bash
tokio --vivo-status     # Ver estado
tokio --vivo-follow     # Seguir output en vivo (tail -f)
tokio --vivo-log        # Ver historial de acciones
tokio --vivo-stop       # Parar
tokio --vivo-reset      # Limpiar estado para fresh start
```

### 3.3 Modo Resume (continuar sesion anterior)
```bash
tokio --vivo-resume
# o
tokio --vivo-resume --bg
```
Retoma la sesion anterior con su memoria, progreso, y objetivo intactos.

### 3.4 Modo Dry-Run (simulacion)
```bash
tokio --vivo --dry-run --objective "..." --autonomy 3
```
Simula todo -- no escribe archivos, no ejecuta comandos destructivos. Perfecto para probar
un objetivo antes de dejarlo suelto.

### 3.5 Modo Sandbox
```bash
tokio --vivo --sandbox-dir /tmp/vivo-sandbox --objective "Crear un microservicio de auth"
```
Solo puede escribir/editar dentro del directorio sandbox. No toca nada fuera.

---

## 4. Git-Safe Coding (v4.0) <a name="git-safe-coding"></a>

### Que garantiza:

| Garantia | Detalle |
|----------|---------|
| **Nunca main/master** | Vivo SIEMPRE trabaja en branches `vivo/*`. Si esta en main, auto-crea `vivo/session-TIMESTAMP` |
| **Syntax check** | Antes de cada commit, chequea syntax de todos los .py modificados |
| **Tests obligatorios** | Tests deben pasar ANTES de commitear (configurable) |
| **Auto-rollback** | Si tests fallan POST-commit, rollback automatico (hard reset) |
| **Push seguro** | Solo puede pushear branches `vivo/*`, nunca protected branches |
| **PR mode** | Crea DRAFT PRs via `gh` o `glab` CLI -- nunca merge directo |
| **Protected paths** | No puede modificar `.env`, `.key`, `.pem`, `Dockerfile` sin review |
| **Immutable paths** | `.git/`, `node_modules/`, `__pycache__/` -- intocables |
| **Commit size limits** | Max 10 archivos por commit, warning en 500+ lineas |
| **Audit trail** | Cada commit/rollback se loggea en `~/.tokioai/vivo/git_audit.jsonl` |

### Como usarlo:

```bash
# Modo basico -- Vivo codea en branch seguro, tests obligatorios
tokio --vivo \
  --objective "Implementar endpoint /api/v2/users con validacion y tests" \
  --autonomy 2 \
  --no-dry-run

# Sin tests obligatorios (para proyectos sin test suite)
tokio --vivo \
  --objective "..." \
  --autonomy 2 \
  --no-git-tests

# Custom test command
tokio --vivo \
  --objective "..." \
  --autonomy 2 \
  --git-test-cmd "npm test"

# Max 5 archivos por commit, 300 lineas max
tokio --vivo \
  --objective "..." \
  --autonomy 2 \
  --git-max-files 5 \
  --git-max-lines 300
```

### Pipeline de un safe commit:

```
1. Asegurar branch vivo/* (crear si no existe)
2. Verificar paths (no .env, no .git/, no .key)
3. Verificar tamanio (max files, max lines)
4. Syntax check (todos los .py modificados)
5. Correr tests (pytest/npm/cargo/go auto-detectado)
6. COMMIT (si todo pasa)
7. Post-commit test verification
8. Si post-commit falla -> AUTO-ROLLBACK (git reset --hard HEAD~1)
9. Log en audit trail
```

### Acciones Git disponibles para el LLM:

| Accion | Descripcion |
|--------|-------------|
| `git_safe_commit` | Commit con pipeline completo de seguridad |
| `git_push` | Push a remote (solo vivo/* branches) |
| `git_create_pr` | Crear Draft PR via gh/glab CLI |
| `git_status` | Ver estado, branch, commits recientes |
| `git_diff` | Ver diff actual |
| `git_rollback` | Deshacer ultimo commit (soft o hard) |

---

## 5. Comandos CLI Completos <a name="comandos-cli"></a>

```bash
# === CONTROL ===
tokio --vivo                    # Iniciar en foreground
tokio --vivo --bg               # Iniciar como daemon
tokio --vivo-resume             # Retomar sesion anterior
tokio --vivo-stop               # Parar
tokio --vivo-status             # Ver estado
tokio --vivo-follow             # Seguir log en vivo
tokio --vivo-log                # Ver historial
tokio --vivo-reset              # Limpiar estado

# === OBJETIVO ===
--objective "texto"             # Objetivo principal (CRITICO - se lo mas especifico posible)

# === AUTONOMIA ===
--autonomy 0                    # Simulacion (no hace nada real)
--autonomy 1                    # Asistido (solo lectura + comandos seguros)
--autonomy 2                    # Trusted (lee, escribe, ejecuta, commitea) [RECOMENDADO]
--autonomy 3                    # Full auto (incluye comandos destructivos)

# === MODELOS ===
--model k2.5                    # Modelo principal (gear2). Aliases: k3, k2.5, k2.7, sonnet, gemini, etc
--gear3-model k3                # Modelo para razonamiento profundo
--dual                          # Activar dual-model mode
--provider openrouter           # Provider: openrouter, kimi

# === BUDGET ===
--budget-hour 2.00              # Max USD por hora
--budget-session 10.00          # Max USD por sesion
--dry-run                       # Simular sin ejecutar
--no-dry-run                    # Forzar ejecucion real

# === TIMING ===
--tick 3.0                      # Segundos entre ciclos (default: 3)
--hours 4                       # Auto-stop despues de N horas (0 = ilimitado)
--report-every 120              # Segundos entre status prints

# === GIT-SAFE ===
--git-safe                      # Activar (on por default)
--no-git-tests                  # No exigir tests antes de commit
--git-auto-rollback             # Auto-rollback si tests fallan post-commit (on por default)
--no-git-auto-rollback          # Desactivar auto-rollback
--git-test-cmd "cmd"            # Comando custom para tests
--git-max-files N               # Max archivos por commit
--git-max-lines N               # Max lineas por commit (warning)

# === SANDBOX ===
--sandbox-dir /path             # Restringir escritura a este directorio

# === VAULT ===
--vault-set KEY VALUE           # Guardar secret encriptado
--vault-list                    # Listar secrets (mascarados)
--vault-delete KEY              # Borrar secret
```

---

## 6. Configuracion Avanzada <a name="configuracion-avanzada"></a>

Config file: `~/.tokioai/vivo/config.yaml`

```yaml
# Se genera automatico, pero podes editarlo manualmente
objective: "Explore and understand this project"
autonomy: 2
dry_run: false

# Timing
tick_interval: 3.0
report_interval: 120.0
max_hours: 0  # 0 = ilimitado

# Budget
budget_hourly_usd: 2.00
budget_daily_usd: 20.00
budget_session_usd: 10.00
gear2_calls_per_hour: 500
gear3_calls_per_hour: 30
max_actions_per_hour: 500
max_destructive_per_hour: 20

# Modelos
gear2_model: moonshotai/kimi-k2.5
gear3_model: moonshotai/kimi-k3
provider: openrouter
dual_model: false

# Git-Safe
git_auto_commit: true
git_branch_prefix: "vivo/"
git_require_tests: true
git_require_review: false
git_auto_rollback: true
git_max_files_per_commit: 10
git_max_lines_per_commit: 500

# Safety
destructive_whitelist:
  - systemctl restart
  - docker restart
  - pip install
  - apt install
  - npm install
blocked_commands:
  - rm -rf /
  - rm -rf ~
  - mkfs
  - "dd if=/dev/zero"
```

### Variables de entorno (override config):
```bash
TOKIO_VIVO_OBJECTIVE="..."
TOKIO_VIVO_AUTONOMY=2
TOKIO_VIVO_BUDGET_HOUR=5.00
TOKIO_VIVO_PROVIDER=openrouter
TOKIO_VIVO_GEAR2_MODEL=moonshotai/kimi-k2.5
TOKIO_VIVO_GEAR3_MODEL=moonshotai/kimi-k3
TOKIO_VIVO_DRY_RUN=false
```

---

## 7. Objetivos: Como Escribirlos <a name="objetivos"></a>

El objetivo es la UNICA guia que tiene Vivo. Un buen objetivo = buen resultado.

### Malo:
```
"Fix bugs"
"Make it better"
"Work on the project"
```

### Bueno:
```
"Analizar el directorio src/api/ y crear un reporte detallado de la arquitectura,
identificando dependencias circulares, funciones sin tests, y code smells.
Guardar el reporte en docs/architecture_report.md"
```

### Excelente (multi-step):
```
"En el proyecto ~/myapp:
1. Leer y entender la estructura del proyecto
2. Identificar el modulo de autenticacion
3. Agregar validacion de JWT en el middleware de Express
4. Escribir tests unitarios para la validacion
5. Asegurar que todos los tests pasan
6. Crear un commit con mensaje descriptivo
7. Generar un reporte final con los cambios realizados"
```

### Tips para objetivos de coding:
- Especificar el lenguaje/framework: "en Python con FastAPI", "en Node.js con Express"
- Especificar donde estan los archivos: "en src/auth/"
- Especificar que tests queres: "con pytest", "con jest"
- Especificar el estilo: "siguiendo los patterns existentes del proyecto"
- Si queres que commitee: usar autonomy 2 y no-dry-run

---

## 8. Modelos y Proveedores <a name="modelos"></a>

### Aliases disponibles:

| Alias | Modelo completo | Uso recomendado |
|-------|----------------|-----------------|
| `k2.5` | moonshotai/kimi-k2.5 | Gear2 default -- buena relacion costo/calidad |
| `k3` | moonshotai/kimi-k3 | Gear3 -- razonamiento profundo |
| `k2.7` | moonshotai/kimi-k2.7-code | Especializado en codigo |
| `sonnet` | anthropic/claude-sonnet-4 | Excelente para codigo |
| `gpt4o` | openai/gpt-4o | Versatil |
| `gpt4o-mini` | openai/gpt-4o-mini | Muy barato, bueno para Gear2 |
| `gemini` | google/gemini-2.0-flash | Rapido y barato |
| `gemini-pro` | google/gemini-2.5-pro-preview | Muy potente |
| `deepseek` | deepseek/deepseek-chat-v3 | Bueno para codigo |
| `qwen` | qwen/qwen3-235b-a22b | Open source potente |
| `llama8b` | meta-llama/llama-3.1-8b-instruct | Ultra barato |
| `llama70b` | meta-llama/llama-3.1-70b-instruct | Buen balance |

### Configuracion recomendada por caso:

**Analisis de codebase (solo lectura):**
```bash
tokio --vivo --model gemini --autonomy 1 --budget-hour 0.50
```

**Coding activo (escribir + tests):**
```bash
tokio --vivo --model k2.5 --dual --gear3-model k3 --autonomy 2 --budget-hour 2.00
```

**Heavy coding (max calidad):**
```bash
tokio --vivo --model sonnet --dual --gear3-model k3 --autonomy 2 --budget-hour 5.00
```

**Bajo presupuesto:**
```bash
tokio --vivo --model gpt4o-mini --autonomy 1 --budget-hour 0.20
```

---

## 9. Seguridad y Autonomia <a name="seguridad"></a>

### Niveles de autonomia:

| Nivel | Nombre | Que puede hacer | Riesgo |
|-------|--------|----------------|--------|
| 0 | SIMULATION | Solo simula, no ejecuta nada | Cero |
| 1 | ASSISTED | Lee archivos, ejecuta comandos seguros (ls, cat, grep, git status) | Bajo |
| 2 | TRUSTED | Todo lo anterior + escribe archivos, edita, commitea, instala paquetes | Medio |
| 3 | FULL AUTO | Todo, incluye rm, restart, reboot, etc | Alto |

**Recomendacion: usar siempre autonomy 2.** Es el sweet spot -- puede trabajar de verdad
sin poder romper cosas criticas.

### Kill switch:
```bash
# Opcion 1: desde otra terminal
tokio --vivo-stop

# Opcion 2: crear archivo
touch ~/.tokioai/vivo/STOP

# Opcion 3: Ctrl+C (si foreground)

# Opcion 4: matar el proceso
kill $(cat ~/.tokioai/vivo/vivo.pid)
```

### Comandos bloqueados (siempre, sin importar autonomia):
- `rm -rf /` y `rm -rf ~`
- `mkfs`, `dd if=/dev/zero`
- Fork bombs
- SSH a hosts remotos no autorizados

### Rate limits:
- Max 500 acciones por hora (configurable)
- Max 20 acciones destructivas por hora
- Budget por hora y por sesion

---

## 10. Project Memory <a name="project-memory"></a>

Vivo tiene memoria persistente que sobrevive context windows y sesiones.
El LLM escribe en ella durante su trabajo y la lee al inicio de cada ciclo.

### Categorias:

| Categoria | Que guardar | Max items |
|-----------|-------------|-----------|
| facts | Descubrimientos sobre el proyecto | 50 |
| decisions | Decisiones importantes tomadas | 30 |
| progress | Lo que ya se hizo | 50 |
| todo | Lo que falta hacer | 30 |
| errors | Errores encontrados y resoluciones | 30 |
| architecture | Notas de arquitectura high-level | 20 |

### Donde vive:
`~/.tokioai/vivo/project_memory.json`

### Limpiar para fresh start:
```bash
tokio --vivo-reset  # Limpia memory, work_log, tokens
```

---

## 11. Stuck Detection y Recovery <a name="stuck-detection"></a>

Vivo detecta automaticamente cuando esta trabado:

| Senal | Threshold | Que hace |
|-------|-----------|----------|
| Misma accion N veces seguidas | 5 | Sugiere cambiar estrategia |
| Mismo archivo leido repetidamente | 3 en ultimas 8 acciones | Sugiere grep o list_dir |
| Mismo error repetido | 3 veces recientes | Sugiere approach diferente |
| Sin progreso (no escribe, no reporta) | 30 pasos | Fuerza cambio de estrategia |
| Mismo edit fallando | 3 veces recientes | Sugiere write_file completo |

Cuando detecta stuck:
1. Genera una "escape strategy" especifica
2. La inyecta en el proximo prompt al LLM
3. Si tiene dual-model, escala a Gear3 para razonamiento mas profundo

---

## 12. Vault (Secrets) <a name="vault"></a>

Vault encriptado para que Vivo pueda usar API keys sin exponerlas.

```bash
# Guardar un secret
tokio --vault-set GITHUB_TOKEN ghp_xxx123
tokio --vault-set OPENAI_API_KEY sk-xxx

# Listar secrets (mascarados)
tokio --vault-list

# Borrar
tokio --vault-delete GITHUB_TOKEN
```

Los secrets se cargan como variables de entorno al iniciar Vivo.
El LLM puede usarlos via `run_cmd` (ej: `curl -H "Authorization: Bearer $GITHUB_TOKEN" ...`)

Encriptacion: AES-256 con key derivada de un keyfile local.

---

## 13. Monitoring y Debugging <a name="monitoring"></a>

### Status rapido:
```bash
tokio --vivo-status
```
Muestra: status, objetivo, modelo, autonomia, steps, costo, ultimas acciones.

### Follow en vivo:
```bash
tokio --vivo-follow
```
Como `tail -f` del log con colores.

### Work log detallado:
```bash
tokio --vivo-log
```
Muestra las ultimas 30 acciones con razonamiento, resultado, y reportes.

### Log raw:
```bash
cat ~/.tokioai/vivo/vivo.log
```

### Git audit trail:
```bash
cat ~/.tokioai/vivo/git_audit.jsonl | python -m json.tool
```
Cada linea es un commit/rollback con timestamp, SHA, branch, files, test status.

### Token usage:
```bash
cat ~/.tokioai/vivo/token_guard.json | python -m json.tool
```

---

## 14. Workflows Reales <a name="workflows"></a>

### Workflow 1: Audit de seguridad
```bash
tokio --vivo \
  --objective "Realizar una auditoria de seguridad completa del directorio src/.
    Buscar: SQL injection, XSS, path traversal, hardcoded credentials,
    insecure deserialization, missing auth checks. Generar reporte en
    docs/security_audit.md con severidad, archivo, linea, y fix sugerido." \
  --model sonnet --autonomy 1 --budget-hour 3.00 --hours 1
```

### Workflow 2: Implementar feature con tests
```bash
tokio --vivo --bg \
  --objective "En ~/myproject:
    1. Leer la estructura del proyecto y entender el patron existente
    2. Implementar un endpoint POST /api/v2/webhooks que:
       - Valide el payload con Pydantic
       - Guarde en la DB con SQLAlchemy
       - Emita evento via Redis pub/sub
    3. Escribir tests unitarios con pytest
    4. Asegurar que todos los tests pasan
    5. Hacer commits descriptivos
    6. Generar reporte final" \
  --model k2.5 --dual --gear3-model k3 \
  --autonomy 2 --no-dry-run \
  --budget-hour 2.00 --hours 3
```

### Workflow 3: Refactoring con proteccion
```bash
tokio --vivo --bg \
  --objective "Refactorizar el modulo src/legacy/ a patron Repository.
    Mantener backward compatibility. No romper tests existentes.
    Commits pequenos y descriptivos." \
  --model k2.7 --autonomy 2 \
  --git-max-files 5 --git-max-lines 200 \
  --budget-hour 2.00 --hours 2
```

### Workflow 4: Monitoreo continuo
```bash
tokio --vivo --bg \
  --objective "Monitorear estos servicios cada 5 minutos:
    - nginx (systemctl status)
    - postgres (pg_isready)
    - redis (redis-cli ping)
    - disco (df -h, alertar si >85%)
    - RAM (free -m, alertar si <500MB libre)
    Si algo falla, reportar inmediatamente." \
  --model gpt4o-mini --autonomy 1 \
  --budget-hour 0.10 --tick 300
```

---

## 15. Limitaciones Actuales <a name="limitaciones"></a>

### Lo que NO puede hacer (hoy):

| Limitacion | Detalle | Workaround |
|-----------|---------|------------|
| Auto-merge PRs | Crea draft PRs, no mergea | Vos aprobas y mergeas |
| Multi-repo | Trabaja en un directorio a la vez | Lanzar una instancia por repo |
| Interactive prompts | No puede responder "yes/no" a installers | Usar flags `-y` en el objetivo |
| Browser/UI testing | No tiene acceso a browser | Usar tests headless (Playwright CLI) |
| Debugging paso a paso | No puede usar debugger interactivo | Usa print/log debugging |
| Container build+run | Puede pero es riesgoso sin review | Autonomy 2 + sandbox |
| DB migrations | Puede generar pero no deberia ejecutar en prod | Generar migration, vos la ejecutas |

### Gotchas:

1. **Context window**: Despues de muchos ciclos, el historial se comprime.
   Por eso es critico que Vivo use `memory_write` frecuentemente.

2. **LLM hallucinations**: A veces genera codigo que "parece" correcto pero no compila.
   El syntax check pre-commit atrapa esto, pero los tests son la verdadera red de seguridad.

3. **Loops**: Puede quedar atrapado intentando lo mismo. El stuck detector
   mitiga esto, pero si ves que esta loopeando, matar y reintenter con objetivo mas claro.

4. **Costo**: Un modelo caro (sonnet, gpt4o) a 500 calls/hr puede costar $5-15/hr.
   Controlar siempre con `--budget-hour`.

---

## 16. Roadmap <a name="roadmap"></a>

### Ya implementado (v4.0):
- [x] Branch isolation automatica (vivo/*)
- [x] Pre-commit pipeline (syntax + tests)
- [x] Auto-rollback on test failure
- [x] Push solo a branches seguros
- [x] PR creation via gh/glab CLI
- [x] Protected/immutable paths
- [x] Commit size limits
- [x] Full audit trail
- [x] 56 unit tests passing

### Proximo (v4.1):
- [ ] LLM diff review antes de commit (self-review)
- [ ] Branch naming inteligente (basado en objetivo)
- [ ] Auto-rebase cuando el base branch avanza
- [ ] Commit message conventions enforced (Conventional Commits)
- [ ] Integration test runner (no solo unit tests)
- [ ] Code coverage tracking

### Futuro (v5.0):
- [ ] Multi-repo support
- [ ] CI/CD pipeline integration (trigger CI, wait for results)
- [ ] Code review mode (analizar PRs de otros y comentar)
- [ ] Pair programming mode (Vivo y humano trabajan juntos)
- [ ] Visual diff approval via dashboard
- [ ] Deployment automation (con approval gates)

---

## Resumen: Como Ponerlo a Codear Seguro

```bash
# 1. Asegurate de tener tests en tu proyecto
# 2. Lanzar Vivo con autonomy 2 y git-safe (default on)

tokio --vivo --bg \
  --objective "OBJETIVO DETALLADO AQUI" \
  --model k2.5 --dual --gear3-model k3 \
  --autonomy 2 --no-dry-run \
  --budget-hour 2.00 --hours 3

# 3. Seguir progreso
tokio --vivo-follow

# 4. Cuando termine, revisar el branch vivo/*
git log vivo/session-*

# 5. Si te gusta, mergear (o crear PR)
git checkout main
git merge vivo/session-XXXXX

# O dejar que Vivo cree el PR:
# (Agregar --git-auto-pr al comando o usar git_create_pr en el objetivo)
```

**Regla de oro**: Vivo codea en su branch, vos aprobas en main. Nunca al reves.
