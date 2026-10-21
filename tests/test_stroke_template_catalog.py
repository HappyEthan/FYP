"""A single offline entry must discover real bundles without altering them."""
import json
from pathlib import Path
import re
import pytest
from urllib.parse import unquote

from brushbot.stroke_templates.bundle import build_bundle, fit_bundle, prepare_bundle
from tests.test_stroke_template_cli import command, fixture


def catalog_data(path):
    text = path.read_text(encoding='utf-8')
    return json.loads(re.search(r'<script id="catalog-data" type="application/json">(.*?)</script>', text, re.S).group(1))


@pytest.mark.parametrize('order',[['永','永'],['永','好字']])
def test_invalid_character_order_cannot_replace_the_existing_catalog(tmp_path,order):
    root=tmp_path/'library'
    assert command('catalog','--root',root).returncode==0
    previous=(root/'index.html').read_bytes()
    (root/'catalog_settings.json').write_text(json.dumps(dict(schema_version=1,
        role='stroke_template_catalog_settings',character_order=order),ensure_ascii=False))
    result=command('catalog','--root',root)
    assert result.returncode!=0
    assert (root/'index.html').read_bytes()==previous


def test_practice_order_keeps_latest_unlisted_character_before_its_partial_draft(tmp_path):
    from brushbot.stroke_templates.annotations import load_font_record,prepare_annotation
    from brushbot.stroke_templates.bundle import write_json
    from brushbot.stroke_templates.examples import _render_font

    root=tmp_path/'library';image=tmp_path/'two.png'
    record=load_font_record('二',Path(__file__).resolve().parents[1]/'data/makemeahanzi/graphics.txt')
    transform=_render_font(record,image,300)
    complete=prepare_annotation(image,'二',font_record=record,font_transform=transform,image_kind='font_fixture')
    for stroke in complete['strokes']:stroke['path_mode']='preserve'
    partial=json.loads(json.dumps(complete));partial['strokes']=partial['strokes'][:1]
    fit_bundle(partial,image,[],root/'characters/old_draft')
    fit_bundle(complete,image,[],root/'characters/new_complete')
    write_json(root/'catalog_settings.json',dict(schema_version=1,
        role='stroke_template_catalog_settings',character_order=['永']))
    result=command('catalog','--root',root)
    assert result.returncode==0,result.stderr
    entries=catalog_data(root/'index.html')['characters']
    assert [e['path'] for e in entries]==['characters/new_complete','characters/old_draft']


def test_build_and_fit_automatically_refresh_the_same_library_home(tmp_path):
    image, annotation, _ = fixture(tmp_path)
    root = tmp_path/'library'
    model = root/'strokes/横 # 1'
    result = command('build', '--annotation', annotation, '--image', image, '--stroke-id', 's01',
        '--style-id', 'test_style', '--output-dir', model, '--catalog-root', root)
    assert result.returncode == 0, result.stderr
    assert (root/'index.html').exists()
    assert len(catalog_data(root/'index.html')['templates']) == 1
    manifest = (model/'manifest.json').read_bytes()
    result = command('fit', '--annotation', annotation, '--image', image, '--templates', model,
        '--output-dir', root/'characters/一/v1', '--catalog-root', root)
    assert result.returncode == 0, result.stderr
    data = catalog_data(root/'index.html')
    assert len(data['templates']) == 1
    assert len(data['characters']) == 1
    assert data['characters'][0]['character'] == '一'
    assert data['characters'][0]['complete'] is True
    assert data['templates'][0]['type'] == 'heng'
    for entry in data['templates']+data['characters']:
        assert (root/unquote(entry['href'])).is_file()
    assert (model/'manifest.json').read_bytes() == manifest


def test_catalog_collects_drafts_and_versions_and_excludes_corrupt_or_unpublished_bundles(tmp_path):
    image, _, annotation = fixture(tmp_path)
    root = tmp_path/'library'
    model = build_bundle([(annotation, image, 's01')], root/'strokes/v1', style_id='test_style')['template']
    fit_bundle(annotation, image, [model], root/'characters/一/v1')
    changed = json.loads(json.dumps(annotation)); changed['strokes'][0]['xy_px'][0][0] += 1
    fit_bundle(changed, image, [model], root/'characters/一/v2')
    prepare_bundle(image, '字', root/'characters/字/draft', no_prior=True)
    build_bundle([(annotation, image, 's01')], root/'.unfinished/model', style_id='hidden_style')
    build_bundle([(annotation, image, 's01')], root/'strokes/broken', style_id='broken_style')
    (root/'strokes/broken/reference_000_source.bin').write_bytes(b'corrupted')
    result = command('catalog', '--root', root)
    assert result.returncode == 0, result.stderr
    data = catalog_data(root/'index.html')
    assert len(data['templates']) == 1
    assert len(data['characters']) == 3
    assert [e['kind'] for e in data['characters']].count('annotation') == 1
    assert len(data['errors']) == 1
    assert 'strokes/broken' in data['errors'][0]['path']
    assert all('.unfinished' not in e['path'] for e in data['templates'])


def test_refresh_cannot_overwrite_a_published_report_or_unmanaged_home(tmp_path):
    image, _, annotation = fixture(tmp_path)
    root = tmp_path/'library'
    build_bundle([(annotation, image, 's01')], root, style_id='test_style')
    original = (root/'manifest.json').read_bytes()
    result = command('catalog', '--root', root)
    assert result.returncode != 0
    assert 'published' in result.stderr
    assert (root/'manifest.json').read_bytes() == original
    assert not (root/'index.html').exists()
    empty = tmp_path/'empty'; empty.mkdir()
    (empty/'index.html').write_text('user page')
    result = command('catalog', '--root', empty)
    assert result.returncode != 0
    assert 'unmanaged' in result.stderr
    assert (empty/'index.html').read_text() == 'user page'


def test_empty_catalog_and_refresh_remove_deleted_entries(tmp_path):
    root = tmp_path/'library'
    result = command('catalog', '--root', root)
    assert result.returncode == 0, result.stderr
    assert catalog_data(root/'index.html')['characters'] == []
    image, _, annotation = fixture(tmp_path)
    model = build_bundle([(annotation, image, 's01')], root/'strokes/heng', style_id='test_style')
    assert command('catalog', '--root', root).returncode == 0
    assert len(catalog_data(root/'index.html')['templates']) == 1
    Path(model['output_dir'], 'manifest.json').unlink()
    assert command('catalog', '--root', root).returncode == 0
    assert catalog_data(root/'index.html')['templates'] == []


def test_catalog_does_not_read_symlinked_artifacts_outside_the_library(tmp_path):
    image, _, annotation = fixture(tmp_path)
    root = tmp_path/'library'
    build_bundle([(annotation, image, 's01')], root/'strokes/heng', style_id='test_style')
    artifact = root/'strokes/heng/reference_000_source.bin'
    outside = tmp_path/'source.bin'; outside.write_bytes(artifact.read_bytes())
    artifact.unlink(); artifact.symlink_to(outside)
    result = command('catalog', '--root', root)
    assert result.returncode == 0, result.stderr
    data = catalog_data(root/'index.html')
    assert data['templates'] == [] and len(data['errors']) == 1


def test_catalog_refresh_supports_the_python_310_hashlib_api(tmp_path, monkeypatch):
    import hashlib
    from brushbot.stroke_templates.catalog import write_catalog
    image, _, annotation = fixture(tmp_path)
    root = tmp_path/'library'
    build_bundle([(annotation, image, 's01')], root/'strokes/heng', style_id='test_style')
    monkeypatch.delattr(hashlib, 'file_digest', raising=False)
    result = write_catalog(root)
    assert result['template_count'] == 1


def test_simple_common_types_sort_before_complex_strokes_while_latest_versions_win(tmp_path):
    from brushbot.stroke_templates.catalog import collect_catalog
    image, _, annotation = fixture(tmp_path)
    root = tmp_path/'library'
    order = [('heng','long'), ('heng','short'), ('shu','standard'), ('pie','standard'),
             ('na','standard'), ('dian','standard'), ('ti','standard'), ('hengzhegou','standard')]
    for i, (kind, variant) in enumerate(order):
        edited = json.loads(json.dumps(annotation))
        edited['strokes'][0].update(type=kind, variant=variant)
        build_bundle([(edited, image, 's01')], root/f'strokes/{i}', style_id='test_style')
    newer = json.loads(json.dumps(annotation)); newer['strokes'][0].update(type='heng', variant='long')
    newer['strokes'][0]['xy_px'][0][0] += 1
    latest = build_bundle([(newer, image, 's01')], root/'strokes/new_heng', style_id='test_style')
    entries = collect_catalog(root)['templates']
    groups = list(dict.fromkeys((e['type'], e['variant']) for e in entries))
    assert groups == order
    assert entries[0]['id'] == latest['template']['template_id']
