from pathlib import Path


def test_pipeline_template_does_not_escape_empty_strings_in_jinja_expression():
    template = Path("app/templates/pipeline_detail.html").read_text(encoding="utf-8")
    assert '\\"\\"' not in template
