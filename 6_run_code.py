import argparse
import json
import os
import sys
import time
import subprocess
from datetime import datetime
from pathlib import Path

# Ordem dos scripts conforme seu pipeline
SCRIPTS_IN_ORDER = [
    "1_detect_tags.py",
    "1.5_detect_NF.py",
    "2_mark_blocks.py",
    "3_associate_tags_with_blocks.py",
    "4_group_blocks.py",
    "4.5_adapt_logical_expression.py",
    "5_build_python_condition.py",
]

def ensure_dir(path: Path):
    """Garante que um diretório exista, criando-o se necessário."""
    path.mkdir(parents=True, exist_ok=True)

def run_step(script: str, env: dict) -> tuple[int, float, str]:
    """Executa um script e retorna (return_code, elapsed_time, stderr)."""
    start = time.time()
    ts = datetime.now().isoformat(timespec="seconds")
    print(f"[{ts}] Iniciando: {script}")
    
    try:
        proc = subprocess.run(
            [sys.executable, script],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        elapsed = time.time() - start
        ok = proc.returncode == 0

        if ok:
            print(f"[OK] {script} em {elapsed:.2f}s")
        else:
            print(f"[ERRO] {script} (rc={proc.returncode}) em {elapsed:.2f}s")
            if proc.stderr:
                print("stderr:")
                print(proc.stderr.strip())

        return proc.returncode, elapsed, proc.stderr.strip()
    except Exception as e:
        elapsed = time.time() - start
        err = f"Exceção ao rodar {script}: {e}"
        print(f"[EXCEÇÃO] {script} em {elapsed:.2f}s -> {e}")
        return -1, elapsed, err

def build_env(overwrite: bool, nf_threshold: float | None) -> dict:
    """Constrói o ambiente de execução para os scripts."""
    env = os.environ.copy()
    if overwrite:
        env["PIPELINE_OVERWRITE"] = "1"
    if nf_threshold is not None:
        env["NF_THRESHOLD"] = str(nf_threshold)
    return env

def parse_args():
    """Processa os argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        description="Executa scripts do pipeline medindo o tempo de cada um."
    )
    parser.add_argument("--skip", nargs="*", default=[], help="Lista de scripts a pular (nomes exatos).")
    parser.add_argument("--overwrite", action="store_true", help="Se presente, sinaliza para sobrescrever saídas.")
    parser.add_argument("--nf-threshold", type=float, default=None, help="Limiar para detecção de NF.")
    return parser.parse_args()

def main():
    args = parse_args()
    env = build_env(overwrite=args.overwrite, nf_threshold=args.nf_threshold)

    print("=== Execução do Pipeline ===")
    print("Scripts na ordem:")
    for s in SCRIPTS_IN_ORDER:
        print(f" - {s}")
    if args.skip:
        print("Pulando etapas:", ", ".join(args.skip))

    results = []
    total_start = time.time()

    for script in SCRIPTS_IN_ORDER:
        if script in args.skip:
            ts = datetime.now().isoformat(timespec="seconds")
            print(f"[SKIP] {script}")
            results.append((script, "skipped", 0.0, ""))
            continue

        rc, elapsed, err = run_step(script, env)
        results.append((script, rc, elapsed, err))
        if rc != 0:
            print("Interrompendo pipeline devido a erro.")
            break

    total_elapsed = time.time() - total_start

    # Sumário
    print("\n=== Sumário da execução ===")
    for script, rc, elapsed, err in results:
        status = "skipped" if rc == "skipped" else ("ok" if rc == 0 else "error")
        print(f"{script}: {status} (t={elapsed:.2f}s)")
        if err and isinstance(rc, int) and rc != 0:
            print(f"  erro: {err}")
    print(f"Tempo total: {total_elapsed:.2f}s")

if __name__ == "__main__":
    main()