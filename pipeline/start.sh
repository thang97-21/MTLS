#!/bin/bash
# ============================================
# MT Publishing Pipeline - VSCodium Startup
# ============================================
# Clean startup script with main menu
# Launches from a single terminal with interactive menu
#
# To use in VSCodium:
#   1. Open terminal (Ctrl+`)
#   2. Run: ./start.sh
# ============================================

# CRITICAL: Clear any buffered input from shell auto-execution IMMEDIATELY
# This prevents shell init code (venv activation, etc.) from being captured as menu input
while IFS= read -r -t 0.1 -u 0 line 2>/dev/null; do :; done || true

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m'

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# Clear screen and show header
clear
echo -e "${CYAN}${BOLD}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       MTL STUDIO - MAIN MENU                                 ║"
echo "║       Japanese Light Novel Translation Sections              ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

# Check Python
find_python() {
    if [ -x "$SCRIPT_DIR/../python_env/bin/python3" ]; then
        echo "$SCRIPT_DIR/../python_env/bin/python3"
    elif [ -x "$SCRIPT_DIR/../python_env/bin/python" ]; then
        echo "$SCRIPT_DIR/../python_env/bin/python"
    elif [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
        echo "$SCRIPT_DIR/.venv/bin/python"
    elif [ -x "$SCRIPT_DIR/venv/bin/python" ]; then
        echo "$SCRIPT_DIR/venv/bin/python"
    elif command -v python3 &> /dev/null; then
        echo "python3"
    elif command -v python &> /dev/null; then
        if python --version 2>&1 | grep -q "Python 3"; then
            echo "python"
        fi
    fi
}

PYTHON_CMD=$(find_python)

if [ -z "$PYTHON_CMD" ]; then
    echo -e "${RED}✗ Error: Python 3.10+ not found${NC}"
    echo ""
    echo "Install Python:"
    echo "  macOS: brew install python3"
    echo "  Linux: sudo apt install python3"
    echo ""
    exit 1
fi

echo -e "${GREEN}✓${NC} Python: $("$PYTHON_CMD" --version)"

# Check/install dependencies
if ! "$PYTHON_CMD" -c "import questionary; import rich" 2>/dev/null; then
    echo -e "${YELLOW}⟳ Installing dependencies...${NC}"
    "$PYTHON_CMD" -m pip install questionary rich -q

    if ! "$PYTHON_CMD" -c "import questionary; import rich" 2>/dev/null; then
        echo -e "${RED}✗ Failed to install dependencies${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓${NC} Dependencies ready"

# Show current config
echo ""
echo -e "${CYAN}Current Configuration:${NC}"
"$PYTHON_CMD" - <<'PY' 2>/dev/null
from pipeline.cli.utils.config_bridge import ConfigBridge

def print_fallback() -> None:
    print("  Language: English (EN)")
    print("  Provider: ANTHROPIC")
    print("  Model: claude-opus-4-6")
    print("  Caching: Enabled")

try:
    config = ConfigBridge()
    config.load()

    lang = str(config.target_language or "en").strip().lower()
    lang_name = config.get_language_config(lang).get("language_name", lang.upper())
    provider = str(config.translator_provider or "anthropic").strip().lower()
    phase2_endpoint = str(config.get("translation.phase2_anthropic_endpoint", "openrouter") or "openrouter").strip().lower()
    phase2_endpoint_label = "ANTHROPIC_OFFICIAL" if phase2_endpoint in {"official", "anthropic", "direct"} else "OPENROUTER"

    print(f"  Language: {lang_name} ({lang.upper()})")
    print(f"  Provider: {provider.upper()}")
    print(f"  Translation Endpoint: {phase2_endpoint_label}")
    print(f"  Model: {config.model}")
    print(f"  Caching: {'Enabled' if config.caching_enabled else 'Disabled'}")

    if provider == "anthropic":
        use_env = bool(config.get("anthropic.use_env_key", False))
        key_src = ".env DIRECT" if use_env else "~/.claude/settings.json PROXY"
        print(f"  Anthropic Key: {key_src}")
except Exception:
    print_fallback()
PY

echo ""

# FINAL cleanup: drain any remaining input before menu starts
while IFS= read -r -t 0.05 -u 0 line 2>/dev/null; do :; done || true

# Ignore task-launch shell command echoes that may leak into stdin and
# accidentally get parsed as menu choices.
is_menu_noise_input() {
    local value="$1"
    # Typical VSCode/task runner contamination observed in this workspace:
    # source "/.../python_env/bin/activate"
    # source /.../.venv/bin/activate
    if [[ "$value" =~ ^source[[:space:]]+\"?.*(\.venv|venv|python_env)/bin/activate\"?$ ]]; then
        return 0
    fi
    # Also ignore direct activation commands (without explicit source).
    if [[ "$value" =~ ^\"?.*(\.venv|venv|python_env)/bin/activate\"?$ ]]; then
        return 0
    fi
    return 1
}

get_latest_volume_id() {
    ls -1t "$SCRIPT_DIR/WORK" 2>/dev/null | grep -E ".*_[0-9]{8}_[a-z0-9]{4}$" | head -1
}

ACTIVE_VOLUME_ID=""

select_volume_id_required() {
    local latest_vol
    local confirm
    local vol_id

    latest_vol=$(get_latest_volume_id)

    if [ -z "$latest_vol" ]; then
        echo -e "${RED}✗ No volumes found in WORK directory${NC}"
        read -r -p "Enter volume ID manually: " vol_id
    else
        echo -e "${GREEN}✓ Auto-detected latest volume:${NC} $latest_vol"
        read -r -p "Use this volume? (Y/n): " confirm
        if [[ "$confirm" =~ ^[Nn]$ ]]; then
            read -r -p "Enter volume ID: " vol_id
        else
            vol_id="$latest_vol"
        fi
    fi

    if [ -z "$vol_id" ]; then
        echo -e "${RED}✗ Volume ID required${NC}"
        return 1
    fi

    SELECTED_VOLUME_ID="$vol_id"
    ACTIVE_VOLUME_ID="$vol_id"
    return 0
}

render_active_volume_context() {
    local latest_vol
    local active_vol
    local active_source

    latest_vol=$(get_latest_volume_id)

    if [ -n "$ACTIVE_VOLUME_ID" ]; then
        active_vol="$ACTIVE_VOLUME_ID"
        active_source="session"
    elif [ -n "$latest_vol" ]; then
        active_vol="$latest_vol"
        active_source="latest"
    else
        active_vol="none"
        active_source="unset"
    fi

    if [ -z "$latest_vol" ]; then
        latest_vol="none"
    fi

    echo "[VOL] Active=$active_vol ($active_source) | Latest=$latest_vol"
}

# Render translator-runtime statistics on the main menu.
render_main_menu_runtime_stats() {
    SCRIPT_DIR_ENV="$SCRIPT_DIR" "$PYTHON_CMD" - <<'PY' 2>/dev/null
from pathlib import Path
import os

def as_int(value, default):
    try:
        return int(value)
    except Exception:
        return int(default)

def as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

def ttl_label_from_minutes(minutes):
    minutes = max(0, as_int(minutes, 0))
    if minutes % 60 == 0 and minutes >= 60:
        return f"{minutes // 60}h"
    return f"{minutes}m"

def format_tokens(value, default="N/A"):
    try:
        num = int(value)
    except Exception:
        return default
    if num >= 1000 and num % 1000 == 0:
        return f"{num // 1000}K"
    return str(num)

def compact_names(items, limit=4):
    vals = [Path(str(v)).stem for v in (items or []) if str(v).strip()]
    if not vals:
        return "-"
    if len(vals) <= limit:
        return ", ".join(vals)
    return ", ".join(vals[:limit]) + f" +{len(vals)-limit}"

root = Path(os.environ.get("SCRIPT_DIR_ENV", ".")).resolve()
config_path = root / "config.yaml"
cfg = {}
try:
    import yaml
    if config_path.exists():
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
except Exception:
    cfg = {}

project = cfg.get("project", {}) or {}
languages = project.get("languages", {}) or {}
target_lang = str(project.get("target_language", "en")).strip().lower()
lang_cfg = languages.get(target_lang, {}) or {}

translation_cfg = cfg.get("translation", {}) or {}
multimodal_cfg = cfg.get("multimodal", {}) or {}
massive_cfg = translation_cfg.get("massive_chapter", {}) or {}
proxy_cfg = cfg.get("proxy", {}) or {}
inference_cfg = proxy_cfg.get("inference", {}) or {}
phase2_endpoint_pref = str(translation_cfg.get("phase2_anthropic_endpoint", "openrouter")).strip().lower()
tool_mode_cfg = translation_cfg.get("tool_mode", {}) or {}
tool_mode_enabled = as_bool(tool_mode_cfg.get("enabled", False), False)

provider = str(cfg.get("translator_provider", "anthropic")).strip().lower()
route_provider = str(inference_cfg.get("provider", "direct")).strip().lower()
if provider == "anthropic":
    if phase2_endpoint_pref in {"official", "anthropic", "direct"}:
        phase2_route = "ANTHROPIC_OFFICIAL"
    elif route_provider == "openrouter":
        phase2_route = "OPENROUTER"
    else:
        phase2_route = "ANTHROPIC_OFFICIAL"
else:
    phase2_route = "N/A"

lang_name = str(lang_cfg.get("language_name", target_lang.upper()))
modules_dir = root / str(lang_cfg.get("modules_dir", "modules/"))
core_modules = sorted([p.name for p in modules_dir.glob("*.md")]) if modules_dir.exists() else []
core_module_count = len(core_modules)
reference_modules = list(lang_cfg.get("reference_modules", []) or [])
reference_count = len(reference_modules)

grammar_rag_cfg = lang_cfg.get("grammar_rag", {}) or {}
grammar_rag_enabled = as_bool(grammar_rag_cfg.get("enabled", False), False)
lookback = as_int((translation_cfg.get("context", {}) or {}).get("lookback_chapters", 2), 2)

vector_cfg = grammar_rag_cfg.get("vector_store", {}) or {}
vector_hint = (
    vector_cfg.get("collection_name")
    or vector_cfg.get("persist_directory")
    or "language pattern stores"
)

if provider == "anthropic":
    anthropic_cfg = cfg.get("anthropic", {}) or {}
    active_model = str(anthropic_cfg.get("model", "claude-sonnet-4-6"))
    active_fallback = str(anthropic_cfg.get("fallback_model", "claude-haiku-4-5-20251001"))
    generation_cfg = anthropic_cfg.get("generation", {}) or {}

    caching_cfg = anthropic_cfg.get("caching", {}) or {}
    cache_enabled = as_bool(caching_cfg.get("enabled", True), True)
    ttl_minutes = as_int(caching_cfg.get("ttl_minutes", 5), 5)
    batch_cfg = anthropic_cfg.get("batch", {}) or {}
    promote_1h = as_bool(batch_cfg.get("promote_cache_ttl_1h", True), True)
    if cache_enabled:
        ttl_label = ttl_label_from_minutes(ttl_minutes)
        if ttl_minutes < 60 and promote_1h:
            cache_ttl = f"{ttl_label} -> 1h(batch) ephemeral"
        else:
            cache_ttl = f"{ttl_label} ephemeral"
    else:
        cache_ttl = "OFF"

    thinking_cfg = anthropic_cfg.get("thinking_mode", {}) or {}
    thinking_enabled = as_bool(thinking_cfg.get("enabled", False), False)
    thinking_type = str(thinking_cfg.get("thinking_type", "adaptive"))
    thinking_active = thinking_enabled
    thinking_mode_label = thinking_type if thinking_active else "OFF"
    thinking_budget = thinking_cfg.get("thinking_budget")
    effort_label = f"budget={thinking_budget}" if thinking_active and thinking_budget is not None else ("adaptive" if thinking_active else "N/A")
    max_out_label = format_tokens(generation_cfg.get("max_output_tokens", "N/A"))

    batch_enabled_cfg = as_bool(batch_cfg.get("enabled", False), False)
    batch_auto_disable = as_bool(tool_mode_cfg.get("auto_disable_for_batch_adaptive_thinking", False), False)
    if tool_mode_enabled and batch_auto_disable:
        batch_hint = "OFF (auto-disabled by tool mode)"
    elif batch_enabled_cfg:
        batch_hint = "ON (config)"
    else:
        batch_hint = "OFF"
else:
    gemini_cfg = cfg.get("gemini", {}) or {}
    active_model = str(gemini_cfg.get("model", "gemini-2.5-pro"))
    active_fallback = str(gemini_cfg.get("fallback_model", "gemini-2.5-flash"))
    generation_cfg = gemini_cfg.get("generation", {}) or {}
    cache_enabled = as_bool((gemini_cfg.get("caching", {}) or {}).get("enabled", True), True)
    ttl_minutes = as_int((gemini_cfg.get("caching", {}) or {}).get("ttl_minutes", 120), 120)
    cache_ttl = ttl_label_from_minutes(ttl_minutes) if cache_enabled else "OFF"
    thinking_active = False
    thinking_mode_label = "N/A"
    effort_label = "N/A"
    max_out_label = format_tokens(generation_cfg.get("max_output_tokens", "N/A"))

multimodal_allowed = as_bool(multimodal_cfg.get("enabled", False), False)
multimodal_default = as_bool(translation_cfg.get("enable_multimodal", False), False)
multimodal_active = multimodal_allowed and multimodal_default
vision_model = str(((multimodal_cfg.get("models", {}) or {}).get("vision", "n/a")))
tool_mode_tools = tool_mode_cfg.get("tools", {}) or {}
tool_aliases = [
    ("declare_translation_parameters", "declare"),
    ("validate_glossary_term", "glossary"),
    ("lookup_cultural_term", "cultural"),
    ("report_translation_qc", "qc"),
    ("flag_structural_constraint", "structural"),
]
if tool_mode_enabled:
    active_tool_labels = [
        label for name, label in tool_aliases
        if as_bool(tool_mode_tools.get(name, True), True)
    ]
    tool_mode_label = ",".join(active_tool_labels) if active_tool_labels else "none"
else:
    tool_mode_label = "OFF"

if provider == "anthropic":
    batch_hint_effective = batch_hint
    tool_mode_label_effective = tool_mode_label
    if phase2_route == "ANTHROPIC_OFFICIAL":
        batch_hint_effective = "ON (official endpoint)"
        tool_mode_label_effective = "OFF (official endpoint profile)"
    elif phase2_route == "OPENROUTER":
        batch_hint_effective = "OFF (OpenRouter route)"
        tool_mode_label_effective = "OFF (OpenRouter adapter)"

rag_status = "RUN" if core_module_count > 0 else "FAIL"
vector_status = "RUN" if grammar_rag_enabled else "TODO"
cache_status = "RUN" if cache_enabled else "TODO"
smart_chunking_enabled = as_bool(massive_cfg.get("enable_smart_chunking", True), True)
chunk_status = "RUN" if smart_chunking_enabled else "TODO"
chunk_threshold_chars = as_int(massive_cfg.get("chunk_threshold_chars", 60000), 60000)
chunk_threshold_bytes = as_int(massive_cfg.get("chunk_threshold_bytes", 120000), 120000)
if multimodal_active:
    multimodal_status = "RUN"
elif multimodal_allowed:
    multimodal_status = "TODO"
else:
    multimodal_status = "FAIL"

print("── Runtime Profile ───────────────────────────────────────────────────────────")
print(
    f"[SYS] Runtime Profile: DONE | {target_lang.upper()} ({lang_name}) | "
    f"Provider={provider.upper()} | Route={route_provider.upper()} | Model={active_model} | Fallback={active_fallback}"
)
print(f"[S10] Translator Endpoint: {'RUN' if provider == 'anthropic' else 'N/A'} | {phase2_route}")
print(
    f"[RAG] Tiered RAG: {rag_status} | T1 Core={core_module_count} | "
    f"T1 Grammar={'ON' if grammar_rag_enabled else 'OFF'} | "
    f"T2 Reference={reference_count} | T3 Lookback={lookback}"
)
print(f"[VEC] Vector Search: {vector_status} | {'ON' if grammar_rag_enabled else 'AUTO'} | Source={vector_hint}")
print(f"[CAC] Context Cache: {cache_status} | {'ON' if cache_enabled else 'OFF'} | TTL={cache_ttl}")
print(
    f"[INF] Smart Chunking: {chunk_status} | {'ON' if smart_chunking_enabled else 'OFF'} | "
    f"Threshold={chunk_threshold_chars}c/{chunk_threshold_bytes}b"
)
print(
    f"[MM ] Multimodal: {multimodal_status} | {'ON' if multimodal_active else 'OFF'} | "
    f"{'Vision=' + vision_model if multimodal_active else 'Hint=--enable-multimodal'}"
)
if provider == "anthropic":
    print(
        f"[INF] Claude Features: {'RUN' if thinking_active else 'TODO'} | "
        f"Thinking={thinking_mode_label} | Effort={effort_label} | MaxOut={max_out_label} | "
        f"Batch={batch_hint_effective} | Tools={tool_mode_label_effective}"
    )

# New compact loaded-RAG list for menu-level observability.
print(
    f"[RAG] Loaded (compact): "
    f"T1[{core_module_count}] {compact_names(core_modules)} | "
    f"T2[{reference_count}] {compact_names(reference_modules)}"
)
print("──────────────────────────────────────────────────────────────────────────────")
PY
}

# Main Menu Loop
while true; do
    clear
    echo ""
    echo -e "${BLUE}${BOLD}═══ MAIN MENU ═══${NC}"
    echo ""
    echo -e "  ${GREEN}1${NC}  Run Pipeline"
    echo -e "  ${GREEN}2${NC}  Preparation (Sections 1-9)"
    echo -e "  ${GREEN}3${NC}  Translation"
    echo -e "  ${GREEN}4${NC}  Build & Export"
    echo -e "  ${GREEN}5${NC}  Volume Operations"
    echo -e "  ${GREEN}6${NC}  Configuration Studio"
    echo -e "  ${GREEN}7${NC}  Diagnostics"
    echo -e "  ${GREEN}8${NC}  OpenRouter Agent"
    echo -e "  ${GREEN}9${NC}  Exit"
    echo ""
    render_active_volume_context
    render_main_menu_runtime_stats
    echo ""
    # Read choice with pre-drain for injected shell-noise lines.
    while true; do
        choice=""
        # Opportunistically consume pre-injected shell lines before prompting.
        if IFS= read -r -t 0 buffered; then
            buffered=$(echo "$buffered" | xargs)
            if is_menu_noise_input "$buffered"; then
                continue
            fi
            if [ -n "$buffered" ]; then
                choice="$buffered"
                # Also drain any extra buffered lines, keeping the last non-noise value.
                while IFS= read -r -t 0 buffered; do
                    buffered=$(echo "$buffered" | xargs)
                    if is_menu_noise_input "$buffered"; then
                        continue
                    fi
                    if [ -n "$buffered" ]; then
                        choice="$buffered"
                    fi
                done 2>/dev/null || true
                break
            fi
        fi

        printf "Choose action [1-9] (R refresh, Q quit): "
        IFS= read -r choice
        choice=$(echo "$choice" | xargs)
        if is_menu_noise_input "$choice"; then
            # Try once to consume the next queued line (common task-runner case).
            if IFS= read -r -t 1 buffered; then
                buffered=$(echo "$buffered" | xargs)
                if [ -n "$buffered" ] && ! is_menu_noise_input "$buffered"; then
                    choice="$buffered"
                    break
                fi
            fi

            # Clear contaminated input line and reprompt silently.
            printf "\r\033[2K"
            continue
        fi
        break
    done
    echo ""

    action_choice=""

    case $choice in
        [Rr])
            continue
            ;;
        [Qq])
            action_choice="17"
            ;;
        1)
            action_choice="1"
            ;;
        2)
            echo -e "${CYAN}${BOLD}Preparation (Sections 1-9)${NC}"
            echo -e "  ${GREEN}1${NC}  Section 1: Librarian"
            echo -e "  ${GREEN}2${NC}  Section 2: Title Philosophy Injection"
            echo -e "  ${GREEN}3${NC}  Section 4: Voice RAG Expansion"
            echo -e "  ${GREEN}4${NC}  Section 5: EPS Backfill"
            echo -e "  ${GREEN}5${NC}  Section 6: Rich Metadata Cache"
            echo -e "  ${GREEN}6${NC}  Section 7: Translator's Guidance Brief"
            echo -e "  ${GREEN}7${NC}  Section 8: Multimodal Processor"
            echo -e "  ${GREEN}8${NC}  Section 5.5: JP Pronoun-Shift Detector (Standalone)"
            echo -e "  ${GREEN}9${NC}  Section 9: Scene Planner"
            echo -e "  ${GREEN}b${NC}  Back"
            read -r -p "Choose preparation action [1-9/b]: " prep_choice
            case "$prep_choice" in
                1) action_choice="2" ;;
                2) action_choice="3" ;;
                3) action_choice="4" ;;
                4) action_choice="5" ;;
                5) action_choice="6" ;;
                6) action_choice="7" ;;
                7) action_choice="8" ;;
                8) action_choice="18" ;;
                9) action_choice="9" ;;
                [Bb]|"") continue ;;
                *)
                    echo -e "${RED}✗ Invalid preparation option.${NC}"
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
            esac
            ;;
        3)
            echo -e "${CYAN}${BOLD}Translation${NC}"
            echo -e "  ${GREEN}1${NC}  Section 10: Translate Chapters"
            echo -e "  ${GREEN}2${NC}  Section 11: Volume Bible Update"
            echo -e "  ${GREEN}b${NC}  Back"
            read -r -p "Choose translation action [1-2/b]: " trans_choice
            case "$trans_choice" in
                1) action_choice="10" ;;
                2) action_choice="11" ;;
                [Bb]|"") continue ;;
                *)
                    echo -e "${RED}✗ Invalid translation option.${NC}"
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
            esac
            ;;
        4)
            action_choice="12"
            ;;
        5)
            echo -e "${CYAN}${BOLD}Volume Operations${NC}"
            echo -e "  ${GREEN}1${NC}  Check Volume Status"
            echo -e "  ${GREEN}2${NC}  List All Volumes"
            echo -e "  ${GREEN}b${NC}  Back"
            read -r -p "Choose volume action [1-2/b]: " volops_choice
            case "$volops_choice" in
                1) action_choice="13" ;;
                2) action_choice="14" ;;
                [Bb]|"") continue ;;
                *)
                    echo -e "${RED}✗ Invalid volume operation option.${NC}"
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
            esac
            ;;
        6)
            action_choice="15"
            ;;
        7)
            echo -e "${CYAN}${BOLD}Diagnostics${NC}"
            echo -e "  ${GREEN}1${NC}  Environment Checks"
            echo -e "  ${GREEN}2${NC}  Key Source Check + Current Config"
            echo -e "  ${GREEN}3${NC}  Guardrail Audit"
            echo -e "  ${GREEN}4${NC}  Command Preview (no write)"
            echo -e "  ${GREEN}b${NC}  Back"
            read -r -p "Choose diagnostics action [1-4/b]: " diag_choice
            case "$diag_choice" in
                1)
                    echo -e "${CYAN}Environment Checks${NC}"
                    echo -e "${GREEN}✓${NC} Python: $($PYTHON_CMD --version 2>/dev/null)"
                    if "$PYTHON_CMD" -c "import questionary, rich" >/dev/null 2>&1; then
                        echo -e "${GREEN}✓${NC} Dependencies: questionary, rich"
                    else
                        echo -e "${RED}✗${NC} Dependencies missing: questionary or rich"
                    fi
                    echo ""
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
                2)
                    "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --show
                    echo ""
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
                3)
                    "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import yaml

cfg = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8")) or {}
translation = cfg.get("translation", {}) or {}
tool_mode = (translation.get("tool_mode", {}) or {}).get("enabled", False)
provider = str(cfg.get("translator_provider", "anthropic") or "anthropic").strip().lower()
endpoint = str(translation.get("phase2_anthropic_endpoint", "openrouter") or "openrouter").strip().lower()
thinking = (cfg.get("anthropic", {}) or {}).get("thinking_mode", {}) or {}
thinking_enabled = bool(thinking.get("enabled", False))

print("Guardrail Audit:")
warnings = []

if provider == "anthropic" and endpoint in {"official", "anthropic", "direct"} and tool_mode:
    warnings.append("Tool mode may be incompatible with official Anthropic endpoint profile.")

if provider == "anthropic" and endpoint == "openrouter" and thinking_enabled:
    warnings.append("Anthropic thinking mode is enabled while routing via OpenRouter; verify runtime behavior.")

if not warnings:
    print("  ✓ No high-risk config combinations detected.")
else:
    for item in warnings:
        print(f"  ⚠ {item}")
PY
                    echo ""
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
                4)
                    echo -e "${CYAN}Command Preview (no write)${NC}"
                    echo "  - Full pipeline: $PYTHON_CMD $SCRIPT_DIR/mtl.py run <input.epub> --verbose"
                    echo "  - Translate:     $PYTHON_CMD $SCRIPT_DIR/mtl.py phase2 <volume_id>"
                    echo "  - Build EPUB:    $PYTHON_CMD $SCRIPT_DIR/mtl.py phase4 <volume_id>"
                    echo ""
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
                [Bb]|"") continue ;;
                *)
                    echo -e "${RED}✗ Invalid diagnostics option.${NC}"
                    read -r -p "Press Enter to continue..."
                    continue
                    ;;
            esac
            ;;
        8)
            action_choice="16"
            ;;
        9)
            action_choice="17"
            ;;
        10|11|12|13|14|15|16|17|18)
            # Backward compatibility for direct old menu numbers.
            action_choice="$choice"
            ;;
        *)
            if [ -n "$choice" ]; then
                echo -e "${RED}✗ Invalid option: $choice. Use 1-9, R (refresh), or Q (quit).${NC}"
                read -r -p "Press Enter to continue..."
            fi
            continue
            ;;
    esac

    case $action_choice in
        1)
            echo -e "${CYAN}Starting Full Pipeline...${NC}"
            echo ""
            
            # List available EPUB files
            INPUT_DIR="$SCRIPT_DIR/INPUT"
            if [ ! -d "$INPUT_DIR" ] || [ -z "$(ls -A "$INPUT_DIR"/*.epub 2>/dev/null)" ]; then
                echo -e "${RED}✗ No EPUB files found in INPUT/ directory${NC}"
                read -r -p "Press Enter to continue..."
                continue
            fi
            
            echo -e "${CYAN}Available EPUB files:${NC}"
            epub_files=()
            while IFS= read -r file; do
                epub_files+=("$file")
            done < <(ls "$INPUT_DIR"/*.epub 2>/dev/null)
            
            for i in "${!epub_files[@]}"; do
                filename=$(basename "${epub_files[$i]}")
                echo -e "  ${GREEN}$((i+1))${NC}  $filename"
            done
            echo ""
            
            read -r -p "Select file number (or 0 to cancel): " file_num
            if [ "$file_num" = "0" ] || [ -z "$file_num" ]; then
                continue
            fi
            
            if ! [[ "$file_num" =~ ^[0-9]+$ ]] || [ "$file_num" -lt 1 ] || [ "$file_num" -gt "${#epub_files[@]}" ]; then
                echo -e "${RED}✗ Invalid selection${NC}"
                read -r -p "Press Enter to continue..."
                continue
            fi
            
            epub_path="${epub_files[$((file_num-1))]}"
            echo -e "${GREEN}Selected: $(basename "$epub_path")${NC}"
            echo ""
            
            read -r -p "Enter volume ID (or press Enter for auto-generate): " vol_id
            if [ -n "$vol_id" ]; then
                ACTIVE_VOLUME_ID="$vol_id"
            fi
            
            use_env_key_flag=""
            read -r -p "Bypass Anthropic proxy API key? (.env fallback) (y/N): " bypass_proxy
            if [[ "$bypass_proxy" =~ ^[Yy] ]]; then
                use_env_key_flag="--use-env-key"
            fi

            if [ -z "$vol_id" ]; then
                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" run "$epub_path" $use_env_key_flag --verbose
                latest_after_run=$(get_latest_volume_id)
                if [ -n "$latest_after_run" ]; then
                    ACTIVE_VOLUME_ID="$latest_after_run"
                fi
            else
                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" run "$epub_path" --id "$vol_id" $use_env_key_flag --verbose
                ACTIVE_VOLUME_ID="$vol_id"
            fi
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        2)
            echo -e "${CYAN}Section 1: Librarian (Standalone Extraction)${NC}"
            echo ""
            
            # List available EPUB files
            INPUT_DIR="$SCRIPT_DIR/INPUT"
            if [ ! -d "$INPUT_DIR" ] || [ -z "$(ls -A "$INPUT_DIR"/*.epub 2>/dev/null)" ]; then
                echo -e "${RED}✗ No EPUB files found in INPUT/ directory${NC}"
                read -r -p "Press Enter to continue..."
                continue
            fi
            
            echo -e "${CYAN}Available EPUB files:${NC}"
            epub_files=()
            while IFS= read -r file; do
                epub_files+=("$file")
            done < <(ls "$INPUT_DIR"/*.epub 2>/dev/null)
            
            for i in "${!epub_files[@]}"; do
                filename=$(basename "${epub_files[$i]}")
                echo -e "  ${GREEN}$((i+1))${NC}  $filename"
            done
            echo ""
            
            read -r -p "Select file number (or 0 to cancel): " file_num
            if [ "$file_num" = "0" ] || [ -z "$file_num" ]; then
                continue
            fi
            
            if ! [[ "$file_num" =~ ^[0-9]+$ ]] || [ "$file_num" -lt 1 ] || [ "$file_num" -gt "${#epub_files[@]}" ]; then
                echo -e "${RED}✗ Invalid selection${NC}"
                read -r -p "Press Enter to continue..."
                continue
            fi
            
            epub_path="${epub_files[$((file_num-1))]}"
            echo -e "${GREEN}Selected: $(basename "$epub_path")${NC}"
            echo ""
            
            # Clear input buffer before prompting
            while IFS= read -r -t 0.1 -u 0 line 2>/dev/null; do :; done || true
            
            read -r -p "Enter volume ID (optional): " vol_id
            if [ -n "$vol_id" ]; then
                ACTIVE_VOLUME_ID="$vol_id"
            fi
            
            if [ -z "$vol_id" ]; then
                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1 "$epub_path"
            else
                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1 "$epub_path" --id "$vol_id"
            fi
            phase1_exit=$?

            if [ "$phase1_exit" -eq 0 ]; then
                target_vol="$vol_id"
                if [ -z "$target_vol" ]; then
                    target_vol=$("$PYTHON_CMD" -c "from pathlib import Path; import sys; work=Path(sys.argv[1]); vols=[p for p in work.iterdir() if p.is_dir() and (p/'manifest.json').exists()]; print(max(vols, key=lambda p: p.stat().st_mtime).name if vols else '')" "$SCRIPT_DIR/WORK")
                    if [ -n "$target_vol" ]; then
                        echo -e "${GREEN}✓ Auto-detected extracted volume:${NC} $target_vol"
                    fi
                fi

                if [ -z "$target_vol" ]; then
                    read -r -p "Enter volume ID to continue to Section 3 + Section 6 (or leave blank to skip): " target_vol
                fi

                if [ -n "$target_vol" ]; then
                    ACTIVE_VOLUME_ID="$target_vol"
                    read -r -p "Continue with Section 3 + Section 6 for '$target_vol'? (Y/n): " continue_meta
                    if [[ ! "$continue_meta" =~ ^[Nn]$ ]]; then
                        "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.5 "$target_vol"
                        phase15_exit=$?
                        if [ "$phase15_exit" -eq 0 ]; then
                            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.55 "$target_vol"
                        else
                            echo -e "${RED}✗ Section 3 failed. Skipping Section 6.${NC}"
                        fi
                    else
                        echo -e "${YELLOW}Skipped Section 3 and Section 6.${NC}"
                    fi
                fi
            fi
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        3)
            echo -e "${CYAN}Section 2: Title Philosophy Injection${NC}"
            echo -e "${YELLOW}Analyzes toc.json and injects title philosophy guidance into the manifest.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.15 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        4)
            echo -e "${CYAN}Section 4: Voice RAG Expansion${NC}"
            echo -e "${YELLOW}Backfills Koji Fox voice fingerprints, signature phrases, and scene intent map.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.51 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        5)
            echo -e "${CYAN}Section 5: EPS Backfill${NC}"
            echo -e "${YELLOW}Backfills chapter emotional_proximity_signals and scene intents without rewriting rich metadata.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.52 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        6)
            echo -e "${CYAN}Section 6: Rich Metadata Cache${NC}"
            echo -e "${YELLOW}Builds full-LN cache + context co-processors before translation.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.55 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        7)
            echo -e "${CYAN}Section 7: Translator's Guidance Brief${NC}"
            echo -e "${YELLOW}Generates a full-volume guidance brief for Anthropic batch translation.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.56 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        8)
            echo -e "${CYAN}Section 8: Multimodal Processor (Illustration Analysis)${NC}"
            echo -e "${YELLOW}Pre-bakes visual analysis for illustrations using Gemini 3 Pro Vision.${NC}"
            echo -e "${YELLOW}Run this AFTER Section 1 and BEFORE Section 10 for visual-enhanced translation.${NC}"
            echo ""
            
            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.6 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        9)
            echo -e "${CYAN}Section 9: Scene Planner${NC}"
            echo -e "${YELLOW}Builds narrative beat + rhythm scaffold before translation.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase1.7 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        18)
            echo -e "${CYAN}Section 5.5: JP Pronoun-Shift Detector (Standalone)${NC}"
            echo -e "${YELLOW}Runs deterministic JP pronoun-shift detection and writes .context/pronoun_shift_events_<lang>.json.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            read -r -p "Target language override [en/vn] (blank = config default): " pronoun_lang
            pronoun_args=()
            if [ -n "$pronoun_lang" ]; then
                pronoun_args+=("--target-language" "$pronoun_lang")
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" pronoun-shift "$SELECTED_VOLUME_ID" "${pronoun_args[@]}"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        10)
            echo -e "${CYAN}Section 10: Translate Chapters${NC}"

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi
            
            use_env_key_flag=""
            read -r -p "Bypass Anthropic proxy API key? (.env fallback) (y/N): " bypass_proxy
            if [[ "$bypass_proxy" =~ ^[Yy] ]]; then
                use_env_key_flag="--use-env-key"
            fi
            
            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase2 "$SELECTED_VOLUME_ID" $use_env_key_flag
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        11)
            echo -e "${CYAN}Section 11: Volume Bible Update${NC}"
            echo -e "${YELLOW}Post-translation continuity synthesis into series bible.${NC}"
            echo ""

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            phase25_flags=()
            read -r -p "QC-cleared output confirmed? (y/N): " qc_cleared
            if [[ "$qc_cleared" =~ ^[Yy] ]]; then
                phase25_flags+=("--qc-cleared")
            fi

            read -r -p "Force regeneration even if context exists? (y/N): " force_phase25
            if [[ "$force_phase25" =~ ^[Yy] ]]; then
                phase25_flags+=("--force")
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase2.5 "$SELECTED_VOLUME_ID" "${phase25_flags[@]}"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        12)
            echo -e "${CYAN}Section 12: Build EPUB${NC}"

            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi

            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" phase4 "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        13)
            echo -e "${CYAN}Check Volume Status${NC}"
            if ! select_volume_id_required; then
                read -r -p "Press Enter to continue..."
                continue
            fi
            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" status "$SELECTED_VOLUME_ID"
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        14)
            echo -e "${CYAN}List All Volumes${NC}"
            "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" list
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        15)
            while true; do
                clear
                echo -e "${CYAN}${BOLD}Configuration Studio${NC}"
                echo ""
                echo -e "  ${GREEN}1${NC}  Runtime Profile (Read-only)"
                echo -e "  ${GREEN}2${NC}  Language & Project"
                echo -e "  ${GREEN}3${NC}  Provider, Endpoint & Routing"
                echo -e "  ${GREEN}4${NC}  Models & Generation"
                echo -e "  ${GREEN}5${NC}  Legacy Quick Toggles"
                echo -e "  ${GREEN}6${NC}  Cache & Chunking"
                echo -e "  ${GREEN}7${NC}  Thinking, Tool Mode & Quality"
                echo -e "  ${GREEN}8${NC}  Multimodal"
                echo -e "  ${GREEN}9${NC}  Proxy, Spend & Safety"
                echo -e "  ${GREEN}10${NC} Logging, Debug & CLI"
                echo -e "  ${GREEN}11${NC} Preset Profiles"
                echo -e "  ${GREEN}b${NC}  Back to Main Menu"
                echo ""
                read -r -p "Choose config category [1-11/b]: " config_choice

                case $config_choice in
                    1)
                        "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --show
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    2)
                        echo -e "${CYAN}Language & Project${NC}"
                        echo -e "  ${GREEN}a${NC}  Set Target Language (Quick)"
                        echo -e "  ${GREEN}b${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}c${NC}  Show Current Config"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a-c/x]: " lang_choice
                        case $lang_choice in
                            a)
                                echo "Available languages: en, vn"
                                read -r -p "Enter language code: " lang
                                if [ -n "$lang" ]; then
                                    "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --language "$lang"
                                else
                                    echo -e "${YELLOW}Skipped (no language entered).${NC}"
                                fi
                                ;;
                            b)
                                echo -e "${CYAN}Safe Edit: Language & Project${NC}"
                                read -r -p "Target language [en/vn] (blank = keep current): " safe_lang
                                read -r -p "Lookback chapters (integer, blank = keep current): " safe_lookback

                                if [ -z "$safe_lang" ] && [ -z "$safe_lookback" ]; then
                                    echo -e "${YELLOW}Skipped (no changes entered).${NC}"
                                else
                                    SAFE_LANG="$safe_lang" SAFE_LOOKBACK="$safe_lookback" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

project = cfg.setdefault("project", {})
languages = project.setdefault("languages", {})
translation = cfg.setdefault("translation", {})
context = translation.setdefault("context", {})

new_lang = os.environ.get("SAFE_LANG", "").strip().lower()
new_lookback_raw = os.environ.get("SAFE_LOOKBACK", "").strip()

changes = []

if new_lang:
    known_langs = set(languages.keys()) if isinstance(languages, dict) else set()
    allowed = known_langs or {"en", "vn"}
    if new_lang not in allowed:
        print(f"✗ Invalid target language: {new_lang}. Allowed: {', '.join(sorted(allowed))}")
        sys.exit(1)
    current_lang = str(project.get("target_language", "en") or "en").strip().lower()
    if new_lang != current_lang:
        changes.append(("project.target_language", current_lang, new_lang))

if new_lookback_raw:
    try:
        new_lookback = int(new_lookback_raw)
    except ValueError:
        print("✗ Invalid lookback: must be an integer")
        sys.exit(1)
    if new_lookback < 0:
        print("✗ Invalid lookback: must be >= 0")
        sys.exit(1)

    current_lookback = context.get("lookback_chapters", 2)
    try:
        current_lookback_int = int(current_lookback)
    except Exception:
        current_lookback_int = 2
    if new_lookback != current_lookback_int:
        changes.append(("translation.context.lookback_chapters", current_lookback_int, new_lookback))

if not changes:
    print("No effective changes to apply.")
    sys.exit(2)

print("Preview changes:")
for key, old, new in changes:
    print(f"  - {key}: {old} -> {new}")
PY
                                    preview_exit=$?
                                    if [ "$preview_exit" -eq 2 ]; then
                                        echo -e "${YELLOW}No effective changes detected.${NC}"
                                    elif [ "$preview_exit" -ne 0 ]; then
                                        echo -e "${RED}✗ Preview failed; no config changes were made.${NC}"
                                    else
                                        read -r -p "Apply these changes and create backup? (y/N): " apply_safe_lang
                                        if [[ "$apply_safe_lang" =~ ^[Yy]$ ]]; then
                                            SAFE_LANG="$safe_lang" SAFE_LOOKBACK="$safe_lookback" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

project = cfg.setdefault("project", {})
languages = project.setdefault("languages", {})
translation = cfg.setdefault("translation", {})
context = translation.setdefault("context", {})

new_lang = os.environ.get("SAFE_LANG", "").strip().lower()
new_lookback_raw = os.environ.get("SAFE_LOOKBACK", "").strip()

applied = []

if new_lang:
    known_langs = set(languages.keys()) if isinstance(languages, dict) else set()
    allowed = known_langs or {"en", "vn"}
    if new_lang not in allowed:
        print(f"✗ Invalid target language: {new_lang}. Allowed: {', '.join(sorted(allowed))}")
        sys.exit(1)
    current_lang = str(project.get("target_language", "en") or "en").strip().lower()
    if new_lang != current_lang:
        project["target_language"] = new_lang
        applied.append(("project.target_language", current_lang, new_lang))

if new_lookback_raw:
    try:
        new_lookback = int(new_lookback_raw)
    except ValueError:
        print("✗ Invalid lookback: must be an integer")
        sys.exit(1)
    if new_lookback < 0:
        print("✗ Invalid lookback: must be >= 0")
        sys.exit(1)

    current_lookback = context.get("lookback_chapters", 2)
    try:
        current_lookback_int = int(current_lookback)
    except Exception:
        current_lookback_int = 2
    if new_lookback != current_lookback_int:
        context["lookback_chapters"] = new_lookback
        applied.append(("translation.context.lookback_chapters", current_lookback_int, new_lookback))

if not applied:
    print("No effective changes to apply.")
    sys.exit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = config_path.with_name(f"config.yaml.bak.{stamp}")
shutil.copy2(config_path, backup_path)

config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print(f"✓ Backup created: {backup_path.name}")
print("✓ Applied changes:")
for key, old, new in applied:
    print(f"  - {key}: {old} -> {new}")
PY
                                        else
                                            echo -e "${YELLOW}Cancelled. No changes written.${NC}"
                                        fi
                                    fi
                                fi
                                ;;
                            c)
                                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --show
                                ;;
                            x|X|"")
                                ;;
                            *)
                                echo -e "${RED}✗ Invalid language/project option.${NC}"
                                ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    3)
                        echo -e "${CYAN}Provider, Endpoint & Routing${NC}"
                        echo -e "  ${GREEN}a${NC}  Toggle Anthropic Proxy Key Source"
                        echo -e "  ${GREEN}b${NC}  Toggle Translation Endpoint (OpenRouter/Anthropic)"
                        echo -e "  ${GREEN}c${NC}  Show Current Config"
                        echo -e "  ${GREEN}d${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a-d/x]: " route_choice
                        case $route_choice in
                            a)
                                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --toggle-proxy-key
                                ;;
                            b)
                                "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
translation = cfg.setdefault("translation", {})

cur = str(translation.get("phase2_anthropic_endpoint", "openrouter") or "openrouter").strip().lower()
new = "official" if cur not in {"official", "anthropic", "direct"} else "openrouter"
translation["phase2_anthropic_endpoint"] = new

config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
label = "ANTHROPIC_OFFICIAL" if new == "official" else "OPENROUTER"
print(f"✓ Translation endpoint set to: {label}")
PY
                                ;;
                            c)
                                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --show
                                ;;
                            d)
                                echo -e "${CYAN}Safe Edit: Provider, Endpoint & Routing${NC}"
                                read -r -p "Endpoint [official/openrouter] (blank = keep current): " safe_endpoint
                                read -r -p "Anthropic use env key [on/off] (blank = keep current): " safe_env_key

                                if [ -z "$safe_endpoint" ] && [ -z "$safe_env_key" ]; then
                                    echo -e "${YELLOW}Skipped (no changes entered).${NC}"
                                else
                                    SAFE_ENDPOINT="$safe_endpoint" SAFE_ENV_KEY="$safe_env_key" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

translation = cfg.setdefault("translation", {})
anthropic = cfg.setdefault("anthropic", {})

endpoint_raw = os.environ.get("SAFE_ENDPOINT", "").strip().lower()
env_key_raw = os.environ.get("SAFE_ENV_KEY", "").strip().lower()

changes = []

if endpoint_raw:
    if endpoint_raw not in {"official", "openrouter"}:
        print("✗ Invalid endpoint. Use: official or openrouter")
        sys.exit(1)
    current_endpoint = str(translation.get("phase2_anthropic_endpoint", "openrouter") or "openrouter").strip().lower()
    if endpoint_raw != current_endpoint:
        changes.append(("translation.phase2_anthropic_endpoint", current_endpoint, endpoint_raw))

if env_key_raw:
    if env_key_raw not in {"on", "off"}:
        print("✗ Invalid env key toggle. Use: on or off")
        sys.exit(1)
    current_env_key = bool(anthropic.get("use_env_key", False))
    target_env_key = env_key_raw == "on"
    if target_env_key != current_env_key:
        changes.append(("anthropic.use_env_key", current_env_key, target_env_key))

if not changes:
    print("No effective changes to apply.")
    sys.exit(2)

print("Preview changes:")
for key, old, new in changes:
    print(f"  - {key}: {old} -> {new}")
PY
                                    preview_exit=$?
                                    if [ "$preview_exit" -eq 2 ]; then
                                        echo -e "${YELLOW}No effective changes detected.${NC}"
                                    elif [ "$preview_exit" -ne 0 ]; then
                                        echo -e "${RED}✗ Preview failed; no config changes were made.${NC}"
                                    else
                                        read -r -p "Apply these changes and create backup? (y/N): " apply_safe_route
                                        if [[ "$apply_safe_route" =~ ^[Yy]$ ]]; then
                                            SAFE_ENDPOINT="$safe_endpoint" SAFE_ENV_KEY="$safe_env_key" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

translation = cfg.setdefault("translation", {})
anthropic = cfg.setdefault("anthropic", {})

endpoint_raw = os.environ.get("SAFE_ENDPOINT", "").strip().lower()
env_key_raw = os.environ.get("SAFE_ENV_KEY", "").strip().lower()

applied = []

if endpoint_raw:
    if endpoint_raw not in {"official", "openrouter"}:
        print("✗ Invalid endpoint. Use: official or openrouter")
        sys.exit(1)
    current_endpoint = str(translation.get("phase2_anthropic_endpoint", "openrouter") or "openrouter").strip().lower()
    if endpoint_raw != current_endpoint:
        translation["phase2_anthropic_endpoint"] = endpoint_raw
        applied.append(("translation.phase2_anthropic_endpoint", current_endpoint, endpoint_raw))

if env_key_raw:
    if env_key_raw not in {"on", "off"}:
        print("✗ Invalid env key toggle. Use: on or off")
        sys.exit(1)
    current_env_key = bool(anthropic.get("use_env_key", False))
    target_env_key = env_key_raw == "on"
    if target_env_key != current_env_key:
        anthropic["use_env_key"] = target_env_key
        applied.append(("anthropic.use_env_key", current_env_key, target_env_key))

if not applied:
    print("No effective changes to apply.")
    sys.exit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = config_path.with_name(f"config.yaml.bak.{stamp}")
shutil.copy2(config_path, backup_path)

config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print(f"✓ Backup created: {backup_path.name}")
print("✓ Applied changes:")
for key, old, new in applied:
    print(f"  - {key}: {old} -> {new}")
PY
                                        else
                                            echo -e "${YELLOW}Cancelled. No changes written.${NC}"
                                        fi
                                    fi
                                fi
                                ;;
                            x|X|"")
                                ;;
                            *)
                                echo -e "${RED}✗ Invalid routing option.${NC}"
                                ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    4)
                        echo -e "${CYAN}Models & Generation${NC}"
                        echo -e "  ${GREEN}a${NC}  Set Model"
                        echo -e "  ${GREEN}b${NC}  Set Temperature"
                        echo -e "  ${GREEN}c${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a-c/x]: " model_choice
                        case $model_choice in
                            a)
                                echo "Available models: flash, pro, 2.5-pro"
                                read -r -p "Enter model: " model
                                if [ -n "$model" ]; then
                                    "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --model "$model"
                                else
                                    echo -e "${YELLOW}Skipped (no model entered).${NC}"
                                fi
                                ;;
                            b)
                                read -r -p "Enter temperature (0.0-2.0): " temp
                                if [ -n "$temp" ]; then
                                    "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --temperature "$temp"
                                else
                                    echo -e "${YELLOW}Skipped (no temperature entered).${NC}"
                                fi
                                ;;
                            c)
                                echo -e "${CYAN}Safe Edit: Models & Generation${NC}"
                                read -r -p "New model (blank = keep current): " safe_model
                                read -r -p "New temperature 0.0-2.0 (blank = keep current): " safe_temp

                                if [ -z "$safe_model" ] && [ -z "$safe_temp" ]; then
                                    echo -e "${YELLOW}Skipped (no changes entered).${NC}"
                                else
                                    SAFE_MODEL="$safe_model" SAFE_TEMP="$safe_temp" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

provider = str(cfg.get("translator_provider", "anthropic") or "anthropic").strip().lower()
if provider not in {"anthropic", "gemini"}:
    provider = "anthropic"

if provider == "anthropic":
    provider_cfg = cfg.setdefault("anthropic", {})
else:
    provider_cfg = cfg.setdefault("gemini", {})

generation_cfg = provider_cfg.setdefault("generation", {})
model_key = "model"
temp_key = "temperature"

new_model = os.environ.get("SAFE_MODEL", "").strip()
new_temp_raw = os.environ.get("SAFE_TEMP", "").strip()

changes = []

current_model = str(provider_cfg.get(model_key, "")).strip()
if new_model and new_model != current_model:
    changes.append((f"{provider}.{model_key}", current_model or "<unset>", new_model))

if new_temp_raw:
    try:
        new_temp = float(new_temp_raw)
    except ValueError:
        print("✗ Invalid temperature: must be a number")
        sys.exit(1)
    if not (0.0 <= new_temp <= 2.0):
        print("✗ Invalid temperature: must be in range 0.0-2.0")
        sys.exit(1)

    current_temp = generation_cfg.get(temp_key)
    if current_temp is None or float(current_temp) != new_temp:
        changes.append((f"{provider}.generation.{temp_key}", current_temp if current_temp is not None else "<unset>", new_temp))

if not changes:
    print("No effective changes to apply.")
    sys.exit(2)

print("Preview changes:")
for key, old, new in changes:
    print(f"  - {key}: {old} -> {new}")
PY
                                    preview_exit=$?
                                    if [ "$preview_exit" -eq 2 ]; then
                                        echo -e "${YELLOW}No effective changes detected.${NC}"
                                    elif [ "$preview_exit" -ne 0 ]; then
                                        echo -e "${RED}✗ Preview failed; no config changes were made.${NC}"
                                    else
                                        read -r -p "Apply these changes and create backup? (y/N): " apply_safe
                                        if [[ "$apply_safe" =~ ^[Yy]$ ]]; then
                                            SAFE_MODEL="$safe_model" SAFE_TEMP="$safe_temp" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

provider = str(cfg.get("translator_provider", "anthropic") or "anthropic").strip().lower()
if provider not in {"anthropic", "gemini"}:
    provider = "anthropic"

if provider == "anthropic":
    provider_cfg = cfg.setdefault("anthropic", {})
else:
    provider_cfg = cfg.setdefault("gemini", {})

generation_cfg = provider_cfg.setdefault("generation", {})
model_key = "model"
temp_key = "temperature"

new_model = os.environ.get("SAFE_MODEL", "").strip()
new_temp_raw = os.environ.get("SAFE_TEMP", "").strip()

applied = []

if new_model:
    current_model = str(provider_cfg.get(model_key, "")).strip()
    if new_model != current_model:
        provider_cfg[model_key] = new_model
        applied.append((f"{provider}.{model_key}", current_model or "<unset>", new_model))

if new_temp_raw:
    try:
        new_temp = float(new_temp_raw)
    except ValueError:
        print("✗ Invalid temperature: must be a number")
        sys.exit(1)
    if not (0.0 <= new_temp <= 2.0):
        print("✗ Invalid temperature: must be in range 0.0-2.0")
        sys.exit(1)

    current_temp = generation_cfg.get(temp_key)
    if current_temp is None or float(current_temp) != new_temp:
        generation_cfg[temp_key] = new_temp
        applied.append((f"{provider}.generation.{temp_key}", current_temp if current_temp is not None else "<unset>", new_temp))

if not applied:
    print("No effective changes to apply.")
    sys.exit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = config_path.with_name(f"config.yaml.bak.{stamp}")
shutil.copy2(config_path, backup_path)

config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print(f"✓ Backup created: {backup_path.name}")
print("✓ Applied changes:")
for key, old, new in applied:
    print(f"  - {key}: {old} -> {new}")
PY
                                        else
                                            echo -e "${YELLOW}Cancelled. No changes written.${NC}"
                                        fi
                                    fi
                                fi
                                ;;
                            x|X|"")
                                ;;
                            *)
                                echo -e "${RED}✗ Invalid models option.${NC}"
                                ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    5)
                        echo -e "${CYAN}Legacy Quick Toggles${NC}"
                        echo -e "  ${GREEN}a${NC}  Toggle Anthropic Proxy Key"
                        echo -e "  ${GREEN}b${NC}  Toggle Translation Endpoint"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a-b/x]: " legacy_choice
                        case $legacy_choice in
                            a)
                                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --toggle-proxy-key
                                ;;
                            b)
                                "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
translation = cfg.setdefault("translation", {})

cur = str(translation.get("phase2_anthropic_endpoint", "openrouter") or "openrouter").strip().lower()
new = "official" if cur not in {"official", "anthropic", "direct"} else "openrouter"
translation["phase2_anthropic_endpoint"] = new

config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
label = "ANTHROPIC_OFFICIAL" if new == "official" else "OPENROUTER"
print(f"✓ Translation endpoint set to: {label}")
PY
                                ;;
                            x|X|"")
                                ;;
                            *)
                                echo -e "${RED}✗ Invalid legacy option.${NC}"
                                ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    6)
                        echo -e "${CYAN}Cache & Chunking${NC}"
                        echo -e "  ${GREEN}a${NC}  Show Current Config"
                        echo -e "  ${GREEN}b${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a-b/x]: " cache_choice
                        case $cache_choice in
                            a)
                                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --show
                                ;;
                            b)
                                echo -e "${CYAN}Safe Edit: Cache & Chunking${NC}"
                                read -r -p "Cache TTL minutes (blank = keep current): " safe_ttl
                                read -r -p "Chunk threshold chars (blank = keep current): " safe_chunk_chars
                                read -r -p "Chunk threshold bytes (blank = keep current): " safe_chunk_bytes

                                if [ -z "$safe_ttl" ] && [ -z "$safe_chunk_chars" ] && [ -z "$safe_chunk_bytes" ]; then
                                    echo -e "${YELLOW}Skipped (no changes entered).${NC}"
                                else
                                    SAFE_TTL="$safe_ttl" SAFE_CHUNK_CHARS="$safe_chunk_chars" SAFE_CHUNK_BYTES="$safe_chunk_bytes" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

provider = str(cfg.get("translator_provider", "anthropic") or "anthropic").strip().lower()
if provider not in {"anthropic", "gemini"}:
    provider = "anthropic"

provider_cfg = cfg.setdefault(provider, {})
caching_cfg = provider_cfg.setdefault("caching", {})
translation = cfg.setdefault("translation", {})
massive = translation.setdefault("massive_chapter", {})

new_ttl_raw = os.environ.get("SAFE_TTL", "").strip()
new_chars_raw = os.environ.get("SAFE_CHUNK_CHARS", "").strip()
new_bytes_raw = os.environ.get("SAFE_CHUNK_BYTES", "").strip()

changes = []

if new_ttl_raw:
    try:
        new_ttl = int(new_ttl_raw)
    except ValueError:
        print("✗ Invalid TTL: must be an integer")
        sys.exit(1)
    if new_ttl <= 0:
        print("✗ Invalid TTL: must be > 0")
        sys.exit(1)
    current_ttl = caching_cfg.get("ttl_minutes", 5 if provider == "anthropic" else 120)
    try:
        current_ttl_int = int(current_ttl)
    except Exception:
        current_ttl_int = 5 if provider == "anthropic" else 120
    if new_ttl != current_ttl_int:
        changes.append((f"{provider}.caching.ttl_minutes", current_ttl_int, new_ttl))

if new_chars_raw:
    try:
        new_chars = int(new_chars_raw)
    except ValueError:
        print("✗ Invalid chunk chars: must be an integer")
        sys.exit(1)
    if new_chars <= 0:
        print("✗ Invalid chunk chars: must be > 0")
        sys.exit(1)
    current_chars = massive.get("chunk_threshold_chars", 60000)
    try:
        current_chars_int = int(current_chars)
    except Exception:
        current_chars_int = 60000
    if new_chars != current_chars_int:
        changes.append(("translation.massive_chapter.chunk_threshold_chars", current_chars_int, new_chars))

if new_bytes_raw:
    try:
        new_bytes = int(new_bytes_raw)
    except ValueError:
        print("✗ Invalid chunk bytes: must be an integer")
        sys.exit(1)
    if new_bytes <= 0:
        print("✗ Invalid chunk bytes: must be > 0")
        sys.exit(1)
    current_bytes = massive.get("chunk_threshold_bytes", 120000)
    try:
        current_bytes_int = int(current_bytes)
    except Exception:
        current_bytes_int = 120000
    if new_bytes != current_bytes_int:
        changes.append(("translation.massive_chapter.chunk_threshold_bytes", current_bytes_int, new_bytes))

if not changes:
    print("No effective changes to apply.")
    sys.exit(2)

print("Preview changes:")
for key, old, new in changes:
    print(f"  - {key}: {old} -> {new}")
PY
                                    preview_exit=$?
                                    if [ "$preview_exit" -eq 2 ]; then
                                        echo -e "${YELLOW}No effective changes detected.${NC}"
                                    elif [ "$preview_exit" -ne 0 ]; then
                                        echo -e "${RED}✗ Preview failed; no config changes were made.${NC}"
                                    else
                                        read -r -p "Apply these changes and create backup? (y/N): " apply_safe_cache
                                        if [[ "$apply_safe_cache" =~ ^[Yy]$ ]]; then
                                            SAFE_TTL="$safe_ttl" SAFE_CHUNK_CHARS="$safe_chunk_chars" SAFE_CHUNK_BYTES="$safe_chunk_bytes" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil
import os
import sys
import yaml

config_path = Path("config.yaml")
cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}

provider = str(cfg.get("translator_provider", "anthropic") or "anthropic").strip().lower()
if provider not in {"anthropic", "gemini"}:
    provider = "anthropic"

provider_cfg = cfg.setdefault(provider, {})
caching_cfg = provider_cfg.setdefault("caching", {})
translation = cfg.setdefault("translation", {})
massive = translation.setdefault("massive_chapter", {})

new_ttl_raw = os.environ.get("SAFE_TTL", "").strip()
new_chars_raw = os.environ.get("SAFE_CHUNK_CHARS", "").strip()
new_bytes_raw = os.environ.get("SAFE_CHUNK_BYTES", "").strip()

applied = []

if new_ttl_raw:
    try:
        new_ttl = int(new_ttl_raw)
    except ValueError:
        print("✗ Invalid TTL: must be an integer")
        sys.exit(1)
    if new_ttl <= 0:
        print("✗ Invalid TTL: must be > 0")
        sys.exit(1)
    current_ttl = caching_cfg.get("ttl_minutes", 5 if provider == "anthropic" else 120)
    try:
        current_ttl_int = int(current_ttl)
    except Exception:
        current_ttl_int = 5 if provider == "anthropic" else 120
    if new_ttl != current_ttl_int:
        caching_cfg["ttl_minutes"] = new_ttl
        applied.append((f"{provider}.caching.ttl_minutes", current_ttl_int, new_ttl))

if new_chars_raw:
    try:
        new_chars = int(new_chars_raw)
    except ValueError:
        print("✗ Invalid chunk chars: must be an integer")
        sys.exit(1)
    if new_chars <= 0:
        print("✗ Invalid chunk chars: must be > 0")
        sys.exit(1)
    current_chars = massive.get("chunk_threshold_chars", 60000)
    try:
        current_chars_int = int(current_chars)
    except Exception:
        current_chars_int = 60000
    if new_chars != current_chars_int:
        massive["chunk_threshold_chars"] = new_chars
        applied.append(("translation.massive_chapter.chunk_threshold_chars", current_chars_int, new_chars))

if new_bytes_raw:
    try:
        new_bytes = int(new_bytes_raw)
    except ValueError:
        print("✗ Invalid chunk bytes: must be an integer")
        sys.exit(1)
    if new_bytes <= 0:
        print("✗ Invalid chunk bytes: must be > 0")
        sys.exit(1)
    current_bytes = massive.get("chunk_threshold_bytes", 120000)
    try:
        current_bytes_int = int(current_bytes)
    except Exception:
        current_bytes_int = 120000
    if new_bytes != current_bytes_int:
        massive["chunk_threshold_bytes"] = new_bytes
        applied.append(("translation.massive_chapter.chunk_threshold_bytes", current_bytes_int, new_bytes))

if not applied:
    print("No effective changes to apply.")
    sys.exit(0)

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup_path = config_path.with_name(f"config.yaml.bak.{stamp}")
shutil.copy2(config_path, backup_path)

config_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")

print(f"✓ Backup created: {backup_path.name}")
print("✓ Applied changes:")
for key, old, new in applied:
    print(f"  - {key}: {old} -> {new}")
PY
                                        else
                                            echo -e "${YELLOW}Cancelled. No changes written.${NC}"
                                        fi
                                    fi
                                fi
                                ;;
                            x|X|"")
                                ;;
                            *)
                                echo -e "${RED}✗ Invalid cache/chunking option.${NC}"
                                ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    7)
                        echo -e "${CYAN}Thinking, Tool Mode & Quality${NC}"
                        echo -e "  ${GREEN}a${NC}  Show Current Config"
                        echo -e "  ${GREEN}b${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a-b/x]: " think_choice
                        case $think_choice in
                            a)
                                "$PYTHON_CMD" "$SCRIPT_DIR/mtl.py" config --show
                                ;;
                            b)
                                read -r -p "Thinking enabled [on/off] (blank keep): " safe_thinking
                                read -r -p "Tool mode enabled [on/off] (blank keep): " safe_tool
                                read -r -p "Max AI-isms per chapter (int, blank keep): " safe_aiisms
                                SAFE_THINKING="$safe_thinking" SAFE_TOOL="$safe_tool" SAFE_AIISMS="$safe_aiisms" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil, os, sys, yaml

cfg_path = Path("config.yaml")
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
anth = cfg.setdefault("anthropic", {})
thinking = anth.setdefault("thinking_mode", {})
translation = cfg.setdefault("translation", {})
tool = translation.setdefault("tool_mode", {})
quality = translation.setdefault("quality", {})

raw_thinking = os.environ.get("SAFE_THINKING", "").strip().lower()
raw_tool = os.environ.get("SAFE_TOOL", "").strip().lower()
raw_aiisms = os.environ.get("SAFE_AIISMS", "").strip()
changes = []

def parse_onoff(value, name):
    if not value:
        return None
    if value not in {"on", "off"}:
        print(f"✗ Invalid {name}: use on/off")
        sys.exit(1)
    return value == "on"

new_thinking = parse_onoff(raw_thinking, "thinking")
if new_thinking is not None and bool(thinking.get("enabled", False)) != new_thinking:
    changes.append(("anthropic.thinking_mode.enabled", bool(thinking.get("enabled", False)), new_thinking))

new_tool = parse_onoff(raw_tool, "tool mode")
if new_tool is not None and bool(tool.get("enabled", False)) != new_tool:
    changes.append(("translation.tool_mode.enabled", bool(tool.get("enabled", False)), new_tool))

if raw_aiisms:
    try:
        aiisms = int(raw_aiisms)
    except ValueError:
        print("✗ Invalid max AI-isms: must be integer")
        sys.exit(1)
    if aiisms < 0:
        print("✗ Invalid max AI-isms: must be >= 0")
        sys.exit(1)
    old = int(quality.get("max_ai_isms_per_chapter", 5))
    if old != aiisms:
        changes.append(("translation.quality.max_ai_isms_per_chapter", old, aiisms))

if not changes:
    print("No effective changes to apply.")
    sys.exit(2)

print("Preview changes:")
for k, old, new in changes:
    print(f"  - {k}: {old} -> {new}")
if any(k == "translation.tool_mode.enabled" and new is True for k, _, new in changes):
    endpoint = str(translation.get("phase2_anthropic_endpoint", "openrouter")).strip().lower()
    if endpoint in {"official", "anthropic", "direct"}:
        print("  ⚠ Guardrail: Tool mode may be incompatible with official endpoint profile.")

confirm = input("Apply these changes and create backup? (y/N): ").strip().lower()
if confirm != "y":
    print("Cancelled. No changes written.")
    sys.exit(0)

for k, _, new in changes:
    if k == "anthropic.thinking_mode.enabled":
        thinking["enabled"] = new
    elif k == "translation.tool_mode.enabled":
        tool["enabled"] = new
    elif k == "translation.quality.max_ai_isms_per_chapter":
        quality["max_ai_isms_per_chapter"] = new

stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = cfg_path.with_name(f"config.yaml.bak.{stamp}")
shutil.copy2(cfg_path, backup)
cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"✓ Backup created: {backup.name}")
PY
                                ;;
                            x|X|"") ;;
                            *) echo -e "${RED}✗ Invalid option.${NC}" ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    8)
                        echo -e "${CYAN}Multimodal${NC}"
                        echo -e "  ${GREEN}a${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a/x]: " mm_choice
                        case $mm_choice in
                            a)
                                read -r -p "translation.enable_multimodal [on/off] (blank keep): " safe_trans_mm
                                read -r -p "multimodal.enabled [on/off] (blank keep): " safe_mm_enabled
                                SAFE_TRANS_MM="$safe_trans_mm" SAFE_MM_ENABLED="$safe_mm_enabled" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil, os, sys, yaml
cfg_path = Path("config.yaml")
cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
translation = cfg.setdefault("translation", {})
mm = cfg.setdefault("multimodal", {})
changes=[]
def parse(v,n):
    v=v.strip().lower()
    if not v: return None
    if v not in {"on","off"}:
        print(f"✗ Invalid {n}: use on/off"); sys.exit(1)
    return v=="on"
t=parse(os.environ.get("SAFE_TRANS_MM",""),"translation.enable_multimodal")
m=parse(os.environ.get("SAFE_MM_ENABLED",""),"multimodal.enabled")
if t is not None and bool(translation.get("enable_multimodal",False))!=t: changes.append(("translation.enable_multimodal", bool(translation.get("enable_multimodal",False)), t))
if m is not None and bool(mm.get("enabled",False))!=m: changes.append(("multimodal.enabled", bool(mm.get("enabled",False)), m))
if not changes: print("No effective changes to apply."); sys.exit(2)
print("Preview changes:")
for k,o,n in changes: print(f"  - {k}: {o} -> {n}")
if any(k=="translation.enable_multimodal" and n for k,_,n in changes) and not bool(mm.get("enabled",False)) and m is None:
    print("  ⚠ Guardrail: translation multimodal ON but multimodal.enabled currently OFF.")
if input("Apply these changes and create backup? (y/N): ").strip().lower()!="y": print("Cancelled. No changes written."); sys.exit(0)
for k,_,n in changes:
    if k=="translation.enable_multimodal": translation["enable_multimodal"]=n
    if k=="multimodal.enabled": mm["enabled"]=n
stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); backup=cfg_path.with_name(f"config.yaml.bak.{stamp}"); shutil.copy2(cfg_path,backup)
cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"✓ Backup created: {backup.name}")
PY
                                ;;
                            x|X|"") ;;
                            *) echo -e "${RED}✗ Invalid option.${NC}" ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    9)
                        echo -e "${CYAN}Proxy, Spend & Safety${NC}"
                        echo -e "  ${GREEN}a${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a/x]: " proxy_choice
                        case $proxy_choice in
                            a)
                                read -r -p "Balance check before run [on/off] (blank keep): " safe_balance
                                read -r -p "Warn threshold USD (blank keep): " safe_warn_usd
                                SAFE_BALANCE="$safe_balance" SAFE_WARN_USD="$safe_warn_usd" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil, os, sys, yaml
cfg_path=Path("config.yaml"); cfg=yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
proxy=cfg.setdefault("proxy",{}); ctrl=proxy.setdefault("control_plane",{}); spend=proxy.setdefault("spend",{})
changes=[]
bal=os.environ.get("SAFE_BALANCE","").strip().lower(); warn=os.environ.get("SAFE_WARN_USD","").strip()
if bal:
    if bal not in {"on","off"}: print("✗ Invalid balance toggle: use on/off"); sys.exit(1)
    new=bal=="on"; old=bool(ctrl.get("balance_check_before_run",True))
    if old!=new: changes.append(("proxy.control_plane.balance_check_before_run",old,new))
if warn:
    try:new=float(warn)
    except ValueError: print("✗ Invalid warn threshold: number required"); sys.exit(1)
    if new<0: print("✗ Invalid warn threshold: must be >= 0"); sys.exit(1)
    old=float(spend.get("warn_threshold_usd",0))
    if old!=new: changes.append(("proxy.spend.warn_threshold_usd",old,new))
if not changes: print("No effective changes to apply."); sys.exit(2)
print("Preview changes:")
for k,o,n in changes: print(f"  - {k}: {o} -> {n}")
if input("Apply these changes and create backup? (y/N): ").strip().lower()!="y": print("Cancelled. No changes written."); sys.exit(0)
for k,_,n in changes:
    if k=="proxy.control_plane.balance_check_before_run": ctrl["balance_check_before_run"]=n
    if k=="proxy.spend.warn_threshold_usd": spend["warn_threshold_usd"]=n
stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); backup=cfg_path.with_name(f"config.yaml.bak.{stamp}"); shutil.copy2(cfg_path,backup)
cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"✓ Backup created: {backup.name}")
PY
                                ;;
                            x|X|"") ;;
                            *) echo -e "${RED}✗ Invalid option.${NC}" ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    10)
                        echo -e "${CYAN}Logging, Debug & CLI${NC}"
                        echo -e "  ${GREEN}a${NC}  Safe Edit (Preview + Confirm + Backup)"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose action [a/x]: " log_choice
                        case $log_choice in
                            a)
                                read -r -p "logging.level [DEBUG/INFO/WARNING/ERROR] (blank keep): " safe_log_level
                                read -r -p "debug.verbose_api [on/off] (blank keep): " safe_verbose_api
                                read -r -p "cli.show_progress [on/off] (blank keep): " safe_show_progress
                                SAFE_LOG_LEVEL="$safe_log_level" SAFE_VERBOSE_API="$safe_verbose_api" SAFE_SHOW_PROGRESS="$safe_show_progress" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil, os, sys, yaml
cfg_path=Path("config.yaml"); cfg=yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
logging_cfg=cfg.setdefault("logging",{}); debug=cfg.setdefault("debug",{}); cli=cfg.setdefault("cli",{})
changes=[]
lvl=os.environ.get("SAFE_LOG_LEVEL","").strip().upper(); vapi=os.environ.get("SAFE_VERBOSE_API","").strip().lower(); prog=os.environ.get("SAFE_SHOW_PROGRESS","").strip().lower()
if lvl:
    if lvl not in {"DEBUG","INFO","WARNING","ERROR"}: print("✗ Invalid logging level"); sys.exit(1)
    old=str(logging_cfg.get("level","INFO")).upper()
    if old!=lvl: changes.append(("logging.level",old,lvl))
def parse(v,name):
    if not v: return None
    if v not in {"on","off"}: print(f"✗ Invalid {name}: use on/off"); sys.exit(1)
    return v=="on"
nv=parse(vapi,"debug.verbose_api")
if nv is not None and bool(debug.get("verbose_api",False))!=nv: changes.append(("debug.verbose_api", bool(debug.get("verbose_api",False)), nv))
np=parse(prog,"cli.show_progress")
if np is not None and bool(cli.get("show_progress",True))!=np: changes.append(("cli.show_progress", bool(cli.get("show_progress",True)), np))
if not changes: print("No effective changes to apply."); sys.exit(2)
print("Preview changes:")
for k,o,n in changes: print(f"  - {k}: {o} -> {n}")
if input("Apply these changes and create backup? (y/N): ").strip().lower()!="y": print("Cancelled. No changes written."); sys.exit(0)
for k,_,n in changes:
    if k=="logging.level": logging_cfg["level"]=n
    elif k=="debug.verbose_api": debug["verbose_api"]=n
    elif k=="cli.show_progress": cli["show_progress"]=n
stamp=datetime.now().strftime("%Y%m%d_%H%M%S"); backup=cfg_path.with_name(f"config.yaml.bak.{stamp}"); shutil.copy2(cfg_path,backup)
cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"✓ Backup created: {backup.name}")
PY
                                ;;
                            x|X|"") ;;
                            *) echo -e "${RED}✗ Invalid option.${NC}" ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    11)
                        echo -e "${CYAN}Preset Profiles${NC}"
                        echo -e "  ${GREEN}1${NC}  Official Production"
                        echo -e "  ${GREEN}2${NC}  OpenRouter Long Context"
                        echo -e "  ${GREEN}3${NC}  Planning/Metadata Economy"
                        echo -e "  ${GREEN}x${NC}  Back"
                        read -r -p "Choose preset [1-3/x]: " preset_choice
                        case $preset_choice in
                            1|2|3)
                                PRESET_ID="$preset_choice" "$PYTHON_CMD" - <<'PY'
from pathlib import Path
from datetime import datetime
import shutil, os, yaml
cfg_path=Path("config.yaml"); cfg=yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
preset=os.environ.get("PRESET_ID")
changes=[]
translation=cfg.setdefault("translation",{})
anth=cfg.setdefault("anthropic",{})
gem=cfg.setdefault("gemini",{})
mm=cfg.setdefault("multimodal",{})

def set_key(container,key,new,label):
    old=container.get(key)
    if old!=new:
        changes.append((label,old,new))
        container[key]=new

if preset=="1":
    set_key(cfg,"translator_provider","anthropic","translator_provider")
    set_key(translation,"phase2_anthropic_endpoint","official","translation.phase2_anthropic_endpoint")
    set_key(translation.setdefault("tool_mode",{}),"enabled",True,"translation.tool_mode.enabled")
    set_key(anth.setdefault("caching",{}),"enabled",True,"anthropic.caching.enabled")
    set_key(anth.setdefault("caching",{}),"ttl_minutes",60,"anthropic.caching.ttl_minutes")
    set_key(translation,"enable_multimodal",True,"translation.enable_multimodal")
    set_key(mm,"enabled",True,"multimodal.enabled")
elif preset=="2":
    set_key(cfg,"translator_provider","anthropic","translator_provider")
    set_key(translation,"phase2_anthropic_endpoint","openrouter","translation.phase2_anthropic_endpoint")
    set_key(translation.setdefault("full_prequel_cache_gate",{}),"enabled",True,"translation.full_prequel_cache_gate.enabled")
    set_key(cfg.setdefault("proxy",{}).setdefault("spend",{}),"warn_threshold_usd",5.0,"proxy.spend.warn_threshold_usd")
elif preset=="3":
    set_key(cfg,"translator_provider","gemini","translator_provider")
    phase_models=translation.setdefault("phase_models",{})
    for key in ["1","1_5","1_55","1_6","1_7","2_5"]:
        old=phase_models.get(key)
        if isinstance(old, dict):
            old_model=old.get("model")
            if old_model!="gemini-2.5-flash-lite":
                changes.append((f"translation.phase_models.{key}.model",old_model,"gemini-2.5-flash-lite"))
                old["model"]="gemini-2.5-flash-lite"
                phase_models[key]=old
        else:
            if old!="gemini-2.5-flash-lite":
                changes.append((f"translation.phase_models.{key}",old,"gemini-2.5-flash-lite"))
                phase_models[key]={"model":"gemini-2.5-flash-lite"}
    set_key(cfg.setdefault("debug",{}),"verbose_api",False,"debug.verbose_api")

if not changes:
    print("No effective changes to apply.")
    raise SystemExit(0)

print("Preview preset changes:")
for k,o,n in changes:
    print(f"  - {k}: {o} -> {n}")

if input("Apply preset and create backup? (y/N): ").strip().lower()!="y":
    print("Cancelled. No changes written.")
    raise SystemExit(0)

stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
backup=cfg_path.with_name(f"config.yaml.bak.{stamp}")
shutil.copy2(cfg_path,backup)
cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True), encoding="utf-8")
print(f"✓ Backup created: {backup.name}")
PY
                                ;;
                            x|X|"") ;;
                            *) echo -e "${RED}✗ Invalid preset option.${NC}" ;;
                        esac
                        echo ""
                        read -r -p "Press Enter to continue..."
                        ;;
                    b|B|"")
                        break
                        ;;
                    *)
                        echo -e "${RED}✗ Invalid option. Choose 1-11 or b.${NC}"
                        read -r -p "Press Enter to continue..."
                        ;;
                esac
            done
            ;;
        16)
            echo -e "${CYAN}OpenRouter Agent (Headless)${NC}"
            agent_dir="$SCRIPT_DIR/openrouter-agent"

            if [ ! -d "$agent_dir" ]; then
                echo -e "${RED}✗ openrouter-agent directory not found: $agent_dir${NC}"
                read -r -p "Press Enter to continue..."
                continue
            fi

            if [ -z "${OPENROUTER_API_KEY:-}" ]; then
                echo -e "${YELLOW}⚠ OPENROUTER_API_KEY is not set in current shell.${NC}"
                echo -e "${YELLOW}  Export it first (or set it in .env loaded by your shell):${NC}"
                echo -e "${YELLOW}  export OPENROUTER_API_KEY=sk-or-...${NC}"
                read -r -p "Press Enter to continue..."
                continue
            fi

            (
                cd "$agent_dir" || exit 1
                if [ ! -d "node_modules" ]; then
                    echo -e "${CYAN}Installing OpenRouter agent dependencies...${NC}"
                    npm install || exit 1
                fi
                npm run start:headless
            )
            echo ""
            read -r -p "Press Enter to continue..."
            ;;
        17)
            echo -e "${CYAN}Goodbye!${NC}"
            exit 0
            ;;
        *)
            if [ -n "$action_choice" ]; then
                echo -e "${RED}✗ Invalid resolved action: $action_choice.${NC}"
            fi
            ;;
    esac
done
