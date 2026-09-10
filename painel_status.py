# -*- coding: utf-8 -*-
"""Painel de acompanhamento das exportacoes Cognos (status + tempos + ETA)."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime
from pathlib import Path

STATUS_FILE = Path(__file__).resolve().parent / "painel_status.json"

# Estimativa inicial por job ate haver media real (Custos costuma demorar mais).
ESTIMATIVA_PADRAO_SEG = 180


def _fmt(segundos: float | int | None) -> str:
    if segundos is None:
        return "--:--"
    s = max(0, int(segundos))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


class PainelAcompanhamento:
    """Escreve painel_status.json e imprime um quadro no console a cada mudanca."""

    def __init__(self, nomes_jobs: list[str], estimativa_padrao: int = ESTIMATIVA_PADRAO_SEG):
        self.inicio = time.time()
        self.estimativa_padrao = estimativa_padrao
        self.fase = "inicio"
        self.mensagem = "Preparando..."
        self.finalizado = False
        self.jobs = [
            {
                "nome": n,
                "status": "PENDENTE",
                "segundos": None,
                "inicio": None,
                "detalhe": "",
            }
            for n in nomes_jobs
        ]
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._tick_loop, daemon=True)
        self.salvar()
        self.imprimir()
        self._thread.start()

    def _tick_loop(self) -> None:
        while not self._stop.wait(2.0):
            with self._lock:
                self._atualizar_rodando()
                self.salvar()

    def _atualizar_rodando(self) -> None:
        agora = time.time()
        for j in self.jobs:
            if j["status"] == "RODANDO" and j["inicio"] is not None:
                j["segundos"] = round(agora - j["inicio"], 1)

    def _eta_segundos(self) -> float:
        concluidos = [j["segundos"] for j in self.jobs if j["status"] not in ("PENDENTE", "RODANDO") and j["segundos"]]
        media = (sum(concluidos) / len(concluidos)) if concluidos else float(self.estimativa_padrao)
        restante = 0.0
        for j in self.jobs:
            if j["status"] == "PENDENTE":
                restante += media
            elif j["status"] == "RODANDO":
                ja = j["segundos"] or 0
                restante += max(0.0, media - ja)
        return restante

    def _payload(self) -> dict:
        self._atualizar_rodando()
        decorrido = time.time() - self.inicio
        return {
            "atualizado_em": datetime.now().isoformat(timespec="seconds"),
            "inicio": datetime.fromtimestamp(self.inicio).strftime("%H:%M:%S"),
            "fase": self.fase,
            "mensagem": self.mensagem,
            "decorrido_segundos": round(decorrido, 1),
            "decorrido": _fmt(decorrido),
            "eta_segundos": round(self._eta_segundos(), 1),
            "eta": _fmt(self._eta_segundos()),
            "finalizado": self.finalizado,
            "jobs": [
                {
                    "nome": j["nome"],
                    "status": j["status"],
                    "segundos": j["segundos"],
                    "tempo": _fmt(j["segundos"]),
                    "detalhe": j["detalhe"],
                }
                for j in self.jobs
            ],
        }

    def salvar(self) -> None:
        STATUS_FILE.write_text(
            json.dumps(self._payload(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def imprimir(self) -> None:
        p = self._payload()
        linhas = [
            "",
            "=" * 72,
            "  COGNOS / Power BI — Painel de Exportacoes",
            f"  Inicio: {p['inicio']}   |   Decorrido: {p['decorrido']}   |   ETA restante: ~{p['eta']}",
            f"  Fase: {p['fase']}   |   {p['mensagem']}",
            "-" * 72,
            f"  {'#':<3} {'Status':<14} {'Tempo':<10} Exportacao",
            "-" * 72,
        ]
        for i, j in enumerate(p["jobs"], 1):
            linhas.append(f"  {i:<3} {j['status']:<14} {j['tempo']:<10} {j['nome']}")
        linhas.append("=" * 72)
        print("\n".join(linhas), flush=True)

    def set_fase(self, fase: str, mensagem: str = "") -> None:
        with self._lock:
            self.fase = fase
            if mensagem:
                self.mensagem = mensagem
            self.salvar()
            self.imprimir()

    def iniciar_job(self, indice: int, mensagem: str = "") -> None:
        with self._lock:
            j = self.jobs[indice]
            j["status"] = "RODANDO"
            j["inicio"] = time.time()
            j["segundos"] = 0
            j["detalhe"] = ""
            self.fase = "exportando"
            self.mensagem = mensagem or f"Executando: {j['nome']}"
            self.salvar()
            self.imprimir()

    def concluir_job(self, indice: int, status: str, detalhe: str = "") -> None:
        with self._lock:
            j = self.jobs[indice]
            if j["inicio"] is not None:
                j["segundos"] = round(time.time() - j["inicio"], 1)
            j["status"] = status
            j["detalhe"] = detalhe
            self.mensagem = f"{j['nome']}: {status}" + (f" — {detalhe}" if detalhe else "")
            self.salvar()
            self.imprimir()

    def finalizar(self, mensagem: str = "Concluido") -> None:
        with self._lock:
            self.finalizado = True
            self.fase = "fim"
            self.mensagem = mensagem
            self.salvar()
            self.imprimir()
        self._stop.set()

    def encerrar(self) -> None:
        self._stop.set()
