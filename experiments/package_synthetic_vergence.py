"""Verify and package the completed synthetic geometry experiment."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from stereofine.config import ALIGNMENT_PIPELINE_VERSION
from stereofine.i18n import Translator
from stereofine.sidecar import load_sidecar, save_sidecar, SidecarStatus
from stereofine.sources import load_source, source_from_stereo_file
from stereofine.state import PairState
from stereofine.status import _vergence_text


def number(value, de=False):
    s = f'{value:.3f}'
    return s.replace('.', ',') if de else s


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    summary = json.loads((out/'summary.json').read_text(encoding='utf-8'))
    rows = summary['cases']
    assert len(rows) == 14 and not any('error' in row for row in rows)
    manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    checks = dict(loaded_full_sbs=[], status_disk_roundtrips=[], projection_checks='passed in generator',
                  numeric_map_inverse_closed_form_check='passed in generator')
    for file in sorted((out/'inputs').glob('*.png')):
        assert hashlib.sha256(file.read_bytes()).hexdigest() == manifest['hashes'][file.name]
        loaded = load_source(source_from_stereo_file(file, file.parent))
        expected = np.asarray(Image.open(file).convert('RGB'))
        assert loaded.left.shape == loaded.right.shape == (2000, 3000, 3)
        assert np.array_equal(loaded.left, expected[:, :3000])
        assert np.array_equal(loaded.right, expected[:, 3000:])
        checks['loaded_full_sbs'].append(file.name)
    states = out/'results'/'state_roundtrips'
    states.mkdir(exist_ok=True)
    for row in rows:
        name = row['case']['name']+'_'+row['method']
        full = json.loads((out/'results'/(name+'.json')).read_text(encoding='utf-8'))
        state = PairState()
        state.alignment.valid = True
        state.alignment.model = row['model']
        state.alignment.method = row['method']
        state.alignment.correction = full['correction']
        file = states/(name+'.sfin')
        save_sidecar(file, state.to_sidecar(source={}))
        loaded = load_sidecar(file)
        assert loaded.status == SidecarStatus.VALID and not loaded.pipeline_mismatches
        restored = PairState.from_sidecar(loaded.document)
        assert _vergence_text(restored, Translator('en')) == row['status_vergence']
        checks['status_disk_roundtrips'].append(name)
    checks['runtime'] = dict(python=platform.python_version(), numpy=np.__version__, opencv=cv2.__version__,
                             pillow=Image.__version__, platform=platform.platform(), pipeline=ALIGNMENT_PIPELINE_VERSION)
    checks['production_files_unchanged'] = subprocess.run(
        ['git', 'diff', '--quiet', 'HEAD', '--', 'stereofine', 'assets', 'StereoFine.py'], cwd=ROOT).returncode == 0
    assert checks['production_files_unchanged']
    checks['source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in (ROOT/'stereofine').glob('*.py')}
    (out/'verification.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    diag = json.loads((out/'known_coordinate_diagnostic.json').read_text(encoding='utf-8'))
    table_en = ['| Case | Method | Selected model | Vergence status | Vertical P95, px | Outer P95, px |',
                '|---|---|---|---|---:|---:|']
    table_de = ['| Fall | Verfahren | Gewähltes Modell | Vergenzstatus | Höhenfehler P95, px | Rand P95, px |',
                '|---|---|---|---|---:|---:|']
    with (out/'results.csv').open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['case', 'method', 'model', 'vergence_status', 'common_controls', 'p95_px', 'outer_p95_px'])
        for row in rows:
            m = row['metrics']['selected']
            values = [row['case']['name'], row['method'], row['model'], row['status_vergence'],
                      row['common_controls'], m['all']['p95'], m['outer_15_percent']['p95']]
            writer.writerow(values)
            for table, de in ((table_en, False), (table_de, True)):
                table.append('| '+' | '.join([*values[:4], number(values[5], de), number(values[6], de)])+' |')
    count = sum('Vergence' in r['model'] for r in rows)
    common_text = (
        '\nInputs: seven lossless grayscale Full-SBS PNGs; 6000 x 2000 pixels, 3000 x 2000 per eye. '
        'Baseline: 65 mm. Horizontal field of view: 60 degrees. Eight finite textured surfaces '
        'at different depths, including tilted panels and a floor, with depth-buffer occlusion. '
        'No lens distortion, photometric noise or moving subjects. All angles are physical camera rotations. '
        'Convergence names give the total angle, split equally between the cameras. '
        'The asymmetric pair uses left/right yaw +0.5/-2 degrees and right pitch/roll +0.4/+0.3 degrees.\n'
        '\nEvery main result uses the normal AKAZE or SIFT entry point at analysis width 3000. '
        'Known world points are never supplied to these feature fits. The evaluation inverts the actual '
        'native maps passed to the production renderer, not the fit residual prediction. '
        'Every variant for one case/method is compared on identical mutually visible retained points; '
        'outer regions are the outer 15% of the original mean projected coordinates. '
        'Control counts can differ between cases/methods. P95 is the 95th percentile of absolute '
        'vertical disparity in native pixels, not a percentage and not a camera angle. '
        'These are coordinate-map residuals, not a measurement of interpolation blur or feature '
        'localization in the resampled picture. Very small numbers are not an exact raster-accuracy claim. '
        'Maximum-error and 3x3-region results are included in the JSON files.\n'
        '\nCounterfactuals reuse existing fitted parameters: affine only, direct quadratic, '
        'projective/vergence only, and projective plus quadratic. A forced counterfactual is not an '
        'accepted product setting. The selected model includes the normal recovery and cubic checks.\n'
        '\nThe separate known-coordinate diagnostic supplies perfect training correspondences, '
        'withholds every fifth control from every fit, and compares the existing first-stage filter '
        'with all known-correct training points. This is a causal diagnostic of the filter, '
        'not a matcher benchmark or a proposal to remove filtering from real photographs.\n'
        '\nNo production geometry, model thresholds, UI, release, original asset or user setting was changed. '
        'SGBM, automatic window framing, color matching and LUTs are outside this geometry experiment. '
        'The status values survive real .sfin save/load roundtrips. These diagnostic .sfin files '
        'are under results/state_roundtrips and are not placed beside the inputs.\n'
    )
    reproduction = (
        '\n## Reproduction\n\nThe three scripts under source/experiments belong in the experiments folder '
        'of the matching StereoFine repository checkout and use its Python dependencies. They are '
        'not a standalone packaged runtime. From the repository root:\n\n'
        '```\npython experiments/synthetic_vergence.py --output build/synthetic-vergence-13\n'
        'python experiments/diagnose_synthetic_vergence.py --output build/synthetic-vergence-13\n'
        'python experiments/package_synthetic_vergence.py --output build/synthetic-vergence-13\n```\n'
        '\nGeneration resets OpenCV RNG seed 1950, uses four threads, and validates camera projection '
        'against cv2.projectPoints, parallel-camera disparity against f*baseline/Z, and map inversion '
        'against an independent closed-form coupled affine inverse. No private input is required.\n'
        '\nPrimary camera-model reference: https://docs.opencv.org/4.13.0/d9/d0c/group__calib3d.html\n'
        '\nThe procedural fixtures and experiment source are supplied under the accompanying MIT license.\n'
    )
    en = ('# StereoFine synthetic vergence test\n\n'
          f'Seven physical stereo pairs, tested with AKAZE and SIFT: **{count} of 14 runs apply the vergence stage**. '
          'The parallel controls do not. Both methods correct the 2-degree convergence pair well. '
          'The 4- and 8-degree pairs expose large remaining errors, sometimes worse than the unaligned input. '
          'They must not be presented as successful alignment results.\n\n'
          'The known-coordinate diagnostic shows that the existing model family can correct these strong '
          'cases much better when all perfect training correspondences are retained. The first-stage '
          'inlier filter can discard useful points even when correspondence error is zero. '
          'This isolates a synthetic failure mode; it does not establish its frequency in real photographs.\n\n'
          'Open inputs/*.png as individual Full-SBS images in StereoFine. Select AKAZE or SIFT and '
          'start a fresh single-image alignment. Maximum aspect ratio makes edge inspection easier. '
          'Existing installed builds can differ; verification.json records the exact tested runtime and source hashes.\n\n'
          +'\n'.join(table_en)+'\n'+common_text+reproduction)
    de = ('# StereoFine: synthetischer Vergenztest\n\n'
          f'**Sieben Stereopaare, 14 Analysen, {count}-mal aktive Vergenzkorrektur.** '
          'Die parallelen Kontrollpaare bleiben ohne diese Zusatzstufe. Bei 2° Gesamt-Konvergenz '
          'liefern beide Verfahren gute geometrische Ergebnisse. Bei 4° und 8° bleiben dagegen '
          'deutliche Höhenfehler; teilweise verschlechtert sich die Geometrie gegenüber der Eingabe.\n\n'
          'Eine getrennte Diagnose mit exakt bekannten Trainingskorrespondenzen zeigt: Die vorhandenen '
          'Korrekturmodelle können diese starken Fälle deutlich besser korrigieren, wenn alle sicher '
          'richtigen Trainingspunkte erhalten bleiben. Schon der erste Punktfilter kann passende '
          'Korrespondenzen verwerfen. Das ist ein synthetisch nachgewiesener Fehlerfall, kein Nachweis '
          'über dessen Häufigkeit bei deinen Fotos. Der Filter wurde im Programm nicht verändert.\n\n'
          'Die verlustfreien Graustufen-PNGs unter inputs sind Full-SBS mit 6000 × 2000 Pixeln '
          '(3000 × 2000 je Halbbild). Die Kamerabasis beträgt 65 mm, der horizontale Bildwinkel 60°. '
          'Die Szene enthält acht Flächen auf verschiedenen Tiefen, auch schräge Tafeln und einen Boden. '
          'Es handelt sich nicht um zwei verzogene Kopien eines flachen Bildes.\n\n'
          '**Ausprobieren:** In StereoFine eine Datei aus inputs als einzelnes Full-SBS-Bild öffnen, '
          'AKAZE oder SIFT wählen und die Justage starten. Zum Prüfen der Ränder das Seitenformat '
          'Maximum wählen. Zuerst bietet sich 02_convergent_2_sbs.png an. '
          'Die Winkel in den Dateinamen sind Gesamtwinkel: bei 2° also jeweils 1° nach innen. '
          'Beim asymmetrischen Paar kommen unterschiedliche Schwenkung, Neigung und Verdrehung zusammen.\n\n'
          +'\n'.join(table_de)+'\n\n'
          'P95 ist die Grenze, unter der 95 % der absoluten Höhenfehler an den gemeinsamen sichtbaren '
          'Kontrollpunkten liegen. Alle Werte sind Pixel in voller Auflösung. Rand bedeutet die äußeren '
          '15 % der ursprünglichen Bildkoordinaten. Die Kontrollpunkte stammen aus der bekannten '
          '3D-Szene und wurden bei den AKAZE-/SIFT-Läufen nicht zum Fitten benutzt. Gemessen wird über '
          'die tatsächlich verwendeten Renderer-Koordinatenkarten. Sehr kleine Werte sind geometrische '
          'Koordinatenfehler und keine Zusicherung entsprechender Raster- oder Bildschärfegenauigkeit.\n\n'
          'Die Zahlen unter Vergenz beschreiben die angewendete Korrektur, keinen gemessenen Kamerawinkel. '
          'Die Statuswerte wurden zusätzlich nach echtem Speichern und Laden einer .sfin überprüft. '
          'Details, Kontrollkoordinaten, Gegenvarianten und die getrennte Diagnose sind beigefügt. '
          'Zur Farbbeurteilung sind diese Graustufen-Testbilder nicht gedacht.\n\n'
          'Die automatisch justierten Vergleichsabbildungen sind verkleinerte JPEG-Ansichtskopien '
          '(Qualität 95, 4:4:4); alle Messungen erfolgten zuvor in voller Auflösung. '
          'Nicht geprüft werden Objektivverzeichnung, Bewegungen, SGBM, Einrahmung oder Exportgeschwindigkeit. '
          'Am Programm und seinen Auswahlgrenzen wurde nichts geändert.\n\n'
          'Die englische README.md enthält Methodik und Reproduktionsanleitung. Die Testdaten und '
          'Experimentquellen stehen unter der beigefügten MIT-Lizenz.\n')
    (out/'README.md').write_text(en, encoding='utf-8')
    (out/'README_DE.md').write_text(de, encoding='utf-8')
    # A viewing contact sheet, not a scientific error plot. No private image.
    canvas = Image.new('RGB', (1500, 1140), '#111111')
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 24)
        caption = ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf', 20)
    except OSError:
        font, caption = ImageFont.load_default(size=24), ImageFont.load_default(size=20)
    draw.text((25, 12), 'StereoFine – synthetischer Vergenztest: 2° Gesamt-Konvergenz', font=font, fill='#c6a95e')
    example = next(r for r in rows if r['case']['name'] == '02_convergent_2' and r['method'] == 'AKAZE')
    example_caption = ('AKAZE: '+example['model']+' · Vergenzstatus '+example['status_vergence'].replace('.', ',')
                       +' · Höhenfehler P95 '+number(example['metrics']['selected']['all']['p95'], True)+' px')
    for y, file, title in ((60, out/'inputs'/'02_convergent_2_sbs.png', 'Eingabe: zwei bekannte Kameras, mehrere Tiefenebenen'),
                            (605, out/'aligned_viewing_copies'/'02_convergent_2_AKAZE_sbs.jpg',
                             example_caption)):
        draw.text((25, y), title, font=caption, fill='#f2f2f2')
        im = Image.open(file).convert('RGB')
        im = ImageOps.contain(im, (1450, 485), Image.Resampling.LANCZOS)
        canvas.paste(im, ((1500-im.width)//2, y+38+(485-im.height)//2))
    canvas.save(out/'Vergenz_2Grad_Vergleich.png')
    sources = out/'source'/'experiments'
    sources.mkdir(parents=True, exist_ok=True)
    for name in ('synthetic_vergence.py', 'diagnose_synthetic_vergence.py', 'package_synthetic_vergence.py'):
        shutil.copyfile(ROOT/'experiments'/name, sources/name)
    shutil.copyfile(ROOT/'LICENSE.txt', out/'LICENSE.txt')
    files = [out/name for name in ('README.md', 'README_DE.md', 'LICENSE.txt', 'manifest.json', 'summary.json',
             'verification.json', 'known_coordinate_diagnostic.json', 'results.csv', 'Vergenz_2Grad_Vergleich.png')]
    files += sorted((out/'inputs').glob('*.png'))
    files += sorted((out/'results').rglob('*'))
    files += sorted(sources.glob('*.py'))
    files += [out/'aligned_viewing_copies'/'02_convergent_2_AKAZE_sbs.jpg',
              out/'aligned_viewing_copies'/'03_convergent_4_AKAZE_sbs.jpg',
              out/'aligned_viewing_copies'/'03_convergent_4_SIFT_sbs.jpg']
    archive = out.parent/'StereoFine_Vergenz_Testbilder.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for file in files:
            if file.is_file():
                z.write(file, file.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        assert len([x for x in z.namelist() if x.startswith('inputs/')]) == 7
        for name, expected_hash in manifest['hashes'].items():
            assert hashlib.sha256(z.read('inputs/'+name)).hexdigest() == expected_hash
    print(json.dumps(dict(archive=str(archive), bytes=archive.stat().st_size,
                          sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                          models=dict(Counter(r['model'] for r in rows)),
                          input_load_checks=len(checks['loaded_full_sbs']),
                          disk_roundtrips=len(checks['status_disk_roundtrips'])), indent=2), flush=True)


if __name__ == '__main__':
    main()
