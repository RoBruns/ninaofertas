from datetime import datetime, timedelta, timezone

from core import relogio


def test_silencio_cruza_meia_noite_e_inicio_igual_fim() -> None:
    janela = {"start": "23:00", "end": "08:00"}
    assert relogio.em_silencio(janela, datetime(2026, 9, 24, 23, 30, tzinfo=relogio.BR))
    assert relogio.em_silencio(janela, datetime(2026, 9, 25, 7, 59, tzinfo=relogio.BR))
    assert relogio.pode_enviar(janela, datetime(2026, 9, 25, 8, 0, tzinfo=relogio.BR))
    desligado = {"start": "08:00", "end": "08:00"}
    assert not relogio.em_silencio(desligado, datetime(2026, 9, 25, 8, 0, tzinfo=relogio.BR))
    assert relogio.pode_enviar(desligado, datetime(2026, 9, 25, 2, 0, tzinfo=relogio.BR))


def test_formatar_hora_naive_local_e_aware() -> None:
    naive = datetime(2026, 9, 24, 12, 34)
    local = naive.replace(tzinfo=datetime.now().astimezone().tzinfo)
    assert relogio.formatar_hora(naive) == local.astimezone(relogio.BR).strftime("%H:%M")
    aware = datetime(2026, 9, 24, 15, 45, tzinfo=timezone.utc)
    assert relogio.formatar_hora(aware) == "12:45"


def test_agora_banco_segue_fuso_do_processo() -> None:
    before = datetime.now()
    value = relogio.agora_banco()
    after = datetime.now()
    assert before - timedelta(seconds=1) <= value <= after + timedelta(seconds=1)
    assert value.tzinfo is None
