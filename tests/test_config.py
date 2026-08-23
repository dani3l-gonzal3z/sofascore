"""Configuración: entorno, .env y precedencias."""

from sofascore.config import Settings, parse_dotenv


def test_valores_por_defecto():
    ajustes = Settings()
    assert ajustes.base_url.startswith("https://")
    assert ajustes.rate_limit > 0
    assert not ajustes.has_plus_credentials()


def test_lectura_de_entorno():
    ajustes = Settings.from_env(
        env={"SOFA_CACHE_TTL": "45", "SOFA_RATE_LIMIT": "1.5", "SOFA_OFFLINE": "sí",
             "SOFA_LANGUAGE": "en"},
        dotenv=None,
    )
    assert ajustes.cache_ttl == 45
    assert ajustes.rate_limit == 1.5
    assert ajustes.offline is True
    assert ajustes.language == "en"


def test_dotenv_y_precedencia(tmp_path):
    fichero = tmp_path / ".env"
    fichero.write_text('SOFA_LANGUAGE=fr\nSOFA_CACHE_TTL=10\n# comentario\nexport SOFA_SPORT="tennis"\n')
    assert parse_dotenv(fichero)["SOFA_SPORT"] == "tennis"

    ajustes = Settings.from_env(env={"SOFA_CACHE_TTL": "99"}, dotenv=fichero)
    assert ajustes.language == "fr"      # viene del .env
    assert ajustes.sport == "tennis"     # con export y comillas
    assert ajustes.cache_ttl == 99       # el entorno gana al .env


def test_overrides_explicitos():
    ajustes = Settings.from_env(env={}, dotenv=None, language="pt", rate_limit=None)
    assert ajustes.language == "pt"
    assert ajustes.rate_limit == Settings().rate_limit  # None no pisa el valor por defecto


def test_redactado_oculta_secretos():
    ajustes = Settings(plus_cookie="sesion=supersecreta")
    resumen = ajustes.redacted()
    assert "supersecreta" not in str(resumen)
    assert resumen["plus_credentials"] == "configuradas"
