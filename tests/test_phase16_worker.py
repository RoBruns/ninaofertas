from contextlib import nullcontext
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx

from core import relogio
from core.platforms.base import OfertaCapturada
from worker import formatter, monitor, promo_instagram, whatsapp


def _oferta(**changes) -> OfertaCapturada:
    values = {
        "nome": "Produto {especial}",
        "preco": 100.0,
        "preco_anterior": 150.0,
        "desconto": 33.3,
        "loja": "Loja {BR}",
        "url": "https://example.com/{item}",
        "capturado_em": datetime(2026, 9, 24, 14, 30, tzinfo=relogio.BR),
    }
    values.update(changes)
    return OfertaCapturada(**values)


def test_formatter_curto_preco_inteiro_sem_preco_e_cupom(monkeypatch) -> None:
    monkeypatch.setattr(formatter, "load_filtros", lambda: {})
    texto = formatter.montar_mensagem(_oferta(codigo_cupom="NINA10"))
    assert "✅ R$ 100" in texto
    assert "100,00" not in texto
    assert "Produto {{especial}}" in texto
    assert texto.index("Cupom: NINA10") < texto.index("https://")

    sem_preco = formatter.montar_mensagem(_oferta(preco=0.0))
    assert "✅ R$" not in sem_preco


def test_formatter_legado_e_campanha(monkeypatch) -> None:
    monkeypatch.setattr(
        formatter,
        "load_filtros",
        lambda: {"mensagem_template": formatter.TEMPLATE_LEGADO},
    )
    assert "De: R$ 150" in formatter.montar_mensagem(_oferta())
    monkeypatch.setattr(
        formatter,
        "load_filtros",
        lambda: {"mensagem_campanha_template": "Campanha {nome} {url} {hora}"},
    )
    texto = formatter.montar_mensagem(_oferta(categoria="campanha", preco=0.0))
    assert texto.startswith("Campanha Produto")
    assert texto.endswith("14:30")


def test_monitor_em_silencio_nao_executa_fontes(monkeypatch) -> None:
    runtime = SimpleNamespace(id=uuid4())
    monkeypatch.setattr(monitor.commands, "drenar_comandos", lambda: None)
    monkeypatch.setattr(monitor.commands, "bot_esta_ativo", lambda _bot_id: True)
    monkeypatch.setattr(monitor, "bot_atual", lambda: runtime)
    monkeypatch.setattr(
        monitor, "load_filtros", lambda: {"quiet_hours": {"start": "00:00", "end": "08:00"}}
    )
    monkeypatch.setattr(monitor.relogio, "em_silencio", lambda _quiet: True)
    monkeypatch.setattr(monitor.relogio, "fim_do_silencio", lambda _quiet: relogio.agora_br())
    monkeypatch.setattr(
        monitor,
        "_executar_ciclo",
        lambda: (_ for _ in ()).throw(AssertionError("nao deve buscar fontes")),
    )
    monitor.ciclo()


def test_monitor_fora_do_silencio_executa_normalmente(monkeypatch) -> None:
    runtime = SimpleNamespace(id=uuid4())
    chamado = []
    monkeypatch.setattr(monitor.commands, "drenar_comandos", lambda: None)
    monkeypatch.setattr(monitor.commands, "bot_esta_ativo", lambda _bot_id: True)
    monkeypatch.setattr(monitor, "bot_atual", lambda: runtime)
    monkeypatch.setattr(monitor, "grupo_db_id", lambda: None)
    monkeypatch.setattr(monitor, "load_filtros", lambda: {"quiet_hours": {"start": "0:00"}})
    monkeypatch.setattr(monitor.relogio, "em_silencio", lambda _quiet: False)
    monkeypatch.setattr(monitor.telemetry, "iniciar_ciclo", lambda *_args: (None, 0.0))
    monkeypatch.setattr(monitor.telemetry, "finalizar_ciclo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        monitor, "_executar_ciclo", lambda: (chamado.append(True), (0, 0, False))[1]
    )
    monitor.ciclo()
    assert chamado == [True]


def test_instagram_respeita_silencio(monkeypatch, tmp_path: Path) -> None:
    foto = tmp_path / "vo.jpg"
    foto.write_bytes(b"foto")
    monkeypatch.setattr(promo_instagram, "FOTO", foto)
    monkeypatch.setattr(promo_instagram, "canais_ativos", lambda: ("canal",))
    monkeypatch.setattr(promo_instagram, "usar_canal", lambda _canal: nullcontext())
    monkeypatch.setattr(
        promo_instagram,
        "load_filtros",
        lambda: {"quiet_hours": {"start": "00:00", "end": "08:00"}},
    )
    monkeypatch.setattr(promo_instagram.relogio, "em_silencio", lambda _quiet: True)
    monkeypatch.setattr(
        promo_instagram,
        "_enviar_canal",
        lambda: (_ for _ in ()).throw(AssertionError("nao deve enviar")),
    )
    promo_instagram.ciclo()


class _Response:
    status_code = 200
    text = "ok"


class _Client:
    calls: list[tuple[str, dict]] = []

    def __init__(self, **_kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url, *, json, headers):
        self.calls.append((url, json))
        return _Response()


def test_whatsapp_midia_recusada_envia_so_texto(monkeypatch, tmp_path: Path) -> None:
    from worker import channels

    _Client.calls = []
    monkeypatch.setattr(httpx, "Client", _Client)
    monkeypatch.setattr(channels, "grupo_whatsapp", lambda: "grupo")
    monkeypatch.setattr(channels, "instancia_evolution", lambda: "instancia")
    fora = tmp_path / "imagem.jpg"
    fora.write_bytes(b"imagem")
    for imagem in ("http://example.com/a.jpg", "https://example.com/a.jpg", str(fora)):
        assert whatsapp.enviar_mensagem("texto", imagem=imagem)
    assert all("/sendText/" in url for url, _payload in _Client.calls)
    assert all(payload == {"number": "grupo", "text": "texto"} for _url, payload in _Client.calls)
