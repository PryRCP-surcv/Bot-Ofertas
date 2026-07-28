import pytest

from bot_ofertas.cli import main


def test_store_list_reports_enabled_adapter(capsys) -> None:
    assert main(["store", "list"]) == 0

    output = capsys.readouterr()
    assert "Coolbox (coolbox) [habilitada]" in output.out
    assert "Oechsle (oechsle) [habilitada]" in output.out
    assert "Promart (promart) [habilitada]" in output.out
    assert "coolbox.pe" in output.out
    assert "oechsle.pe" in output.out
    assert "promart.pe" in output.out
    assert output.err == ""


def test_product_add_rejects_unknown_domain_before_database_access(capsys) -> None:
    result = main(
        [
            "product",
            "add",
            "https://unknown.example.test/product",
            "--label",
            "Producto desconocido",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert "no existe un adaptador" in output.err
    assert "coolbox.pe" in output.err


@pytest.mark.parametrize(
    ("url", "display_name"),
    [
        ("https://www.oechsle.pe/producto-demo/p", "Oechsle"),
        ("https://www.promart.pe/producto-demo/p", "Promart"),
    ],
)
def test_product_add_enforces_each_phase2_store_interval_before_database_access(
    url: str,
    display_name: str,
    capsys,
) -> None:
    result = main(
        [
            "product",
            "add",
            url,
            "--label",
            "Producto piloto",
            "--interval",
            "30",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert f"{display_name} requiere un intervalo mínimo de 60 minutos" in output.err


def test_product_add_rejects_variant_keys_that_collide_after_normalization(
    capsys,
) -> None:
    result = main(
        [
            "product",
            "add",
            "https://unknown.example.test/product",
            "--label",
            "Producto ambiguo",
            "--variant",
            "Color=Negro",
            "--variant",
            "cólor=Azul",
        ]
    )

    output = capsys.readouterr()
    assert result == 2
    assert "cada clave de --variant debe ser única" in output.err
