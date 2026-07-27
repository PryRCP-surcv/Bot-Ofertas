from bot_ofertas.cli import main


def test_store_list_reports_enabled_adapter(capsys) -> None:
    assert main(["store", "list"]) == 0

    output = capsys.readouterr()
    assert "Coolbox (coolbox) [habilitada]" in output.out
    assert "coolbox.pe" in output.out
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
