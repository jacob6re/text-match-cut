#!/usr/bin/env python3
"""Align measured webpage keyword boxes, remap fisheye, build a HyperFrames project."""
import argparse
import hashlib
import html
import json
import math
import shutil
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageDraw


def film_change(sample_rate=48000):
    """Original synthetic film advance: short mechanical clicks plus dry strip rustle."""
    length = 0.075
    t = np.arange(round(length * sample_rate), dtype=np.float64) / sample_rate
    rng = np.random.default_rng(716)
    noise = rng.standard_normal(len(t))
    # High-pass dry rustle, not a continuous projector bed.
    rustle = noise - np.convolve(noise, np.ones(12) / 12, mode='same')
    envelope = np.minimum(t / 0.003, 1) * np.exp(-t / 0.018)
    sound = rustle * envelope * 0.16
    for offset, amplitude in [(0.002, 0.8), (0.022, 0.42), (0.043, 0.22)]:
        local = t - offset
        active = local >= 0
        phase = np.maximum(local, 0)
        sound += amplitude * active * np.exp(-phase / 0.004) * (
            np.sin(2 * np.pi * 1900 * phase) + 0.45 * np.sin(2 * np.pi * 3300 * phase))
    sound *= np.minimum((length - t) / 0.006, 1)
    return sound / max(np.max(np.abs(sound)), 1e-8)


def write_cut_audio(assets, timings, total_frames, fps, source, gain):
    """Freeze one per-cut pulse into a single waveform, with no overlapping tails."""
    sample_rate = 48000
    if source:
        with wave.open(str(source), 'rb') as wav:
            if wav.getsampwidth() != 2 or wav.getnchannels() not in [1, 2]:
                raise ValueError('Custom SFX must be 16-bit PCM mono/stereo WAV')
            sample_rate = wav.getframerate()
            pulse = np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype(np.float64) / 32768
            pulse = pulse.reshape(-1, wav.getnchannels()).mean(axis=1)
        if not len(pulse) or np.max(np.abs(pulse)) < 1e-8:
            raise ValueError('Custom SFX is empty or silent')
        pulse /= np.max(np.abs(pulse))
    else:
        pulse = film_change(sample_rate)
    full = np.zeros(round(total_frames * sample_rate / fps), dtype=np.float64)
    events = []
    for clip in timings[1:]:
        start = round(clip['start_frame'] * sample_rate / fps)
        # Keep the click below one cut interval, with a 3 ms fade when trimming.
        count = min(len(pulse), round(clip['frames'] * sample_rate / fps), len(full) - start)
        fragment = pulse[:count].copy()
        fade = min(round(sample_rate * 0.003), count)
        fragment[-fade:] *= np.linspace(1, 0, fade)
        full[start:start + count] += fragment * gain
        events.append({'frame': clip['start_frame'], 'sample': start})
    with wave.open(str(assets / 'film-changes.wav'), 'wb') as wav:
        wav.setparams((1, 2, sample_rate, len(full), 'NONE', 'not compressed'))
        wav.writeframes((np.clip(full, -1, 1) * 32767).astype('<i2').tobytes())
    return {'source': str(source.resolve()) if source else 'original procedural film-advance imitation',
            'gain': gain, 'sample_rate': sample_rate, 'events': events}


def align_frame(image, box, width, height, target_height, strength, blur):
    """Inverse radial map; center patch remains affine so letters are preserved."""
    source = np.asarray(image.convert('RGB'), dtype=np.float32)
    sh, sw = source.shape[:2]
    scale = target_height / box['height']
    anchor_x = box['x'] + box['width'] / 2
    anchor_y = box['y'] + box['height'] / 2
    cx, cy = width / 2, height / 2
    radius = math.hypot(width, height) / 2
    # Protect the entire keyword rectangle, including long phrases, before bending edges.
    protected = max(0.12, math.hypot(box['width'] * scale / 2 + 6, target_height / 2 + 6) / radius)
    output = np.empty((height, width, 3), dtype=np.uint8)
    xs = np.arange(width, dtype=np.float32)[None, :] + 0.5 - cx
    for row in range(0, height, 128):
        ys = np.arange(row, min(row + 128, height), dtype=np.float32)[:, None] + 0.5 - cy
        distance = np.sqrt(xs * xs + ys * ys) / radius
        bend = np.maximum(distance - protected, 0) / max(1 - protected, 0.1)
        factor = 1 + strength * bend * bend
        src_x = anchor_x + xs * factor / scale - 0.5
        src_y = anchor_y + ys * factor / scale - 0.5
        valid = (src_x >= 0) & (src_x <= sw - 1) & (src_y >= 0) & (src_y <= sh - 1)
        x0 = np.floor(np.clip(src_x, 0, sw - 1)).astype(np.int32)
        y0 = np.floor(np.clip(src_y, 0, sh - 1)).astype(np.int32)
        x1, y1 = np.minimum(x0 + 1, sw - 1), np.minimum(y0 + 1, sh - 1)
        fx = np.clip(src_x - x0, 0, 1)[..., None]
        fy = np.clip(src_y - y0, 0, 1)[..., None]
        pixels = ((source[y0, x0] * (1 - fx) + source[y0, x1] * fx) * (1 - fy)
                  + (source[y1, x0] * (1 - fx) + source[y1, x1] * fx) * fy)
        # White canvas outside the real screenshot: no invented or mirrored context.
        pixels[~valid] = 255
        output[row:row + len(ys)] = np.clip(pixels, 0, 255).astype(np.uint8)
    result = Image.fromarray(output)
    if blur > 0:
        soft = np.asarray(result.filter(ImageFilter.GaussianBlur(blur)), dtype=np.float32)
        dx = np.arange(width, dtype=np.float32)[None, :] + 0.5 - cx
        dy = np.arange(height, dtype=np.float32)[:, None] + 0.5 - cy
        distance = np.sqrt(dx * dx + dy * dy) / radius
        mask = np.clip((distance - protected) / max(1 - protected, 0.1), 0, 1)[..., None]
        result = Image.fromarray(np.clip(output * (1 - mask) + soft * mask, 0, 255).astype(np.uint8))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--gsap', type=Path, required=True)
    parser.add_argument('--width', type=int, default=1080)
    parser.add_argument('--height', type=int, default=1920)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--hold-frames', type=int, default=3)
    parser.add_argument('--last-hold-frames', type=int, default=9)
    parser.add_argument('--keyword-height', type=float)
    parser.add_argument('--fisheye', type=float, default=0.55)
    parser.add_argument('--blur', type=float, default=1.6)
    parser.add_argument('--sfx', type=Path, help='Optional real film-change 16-bit PCM WAV')
    parser.add_argument('--sfx-gain', type=float, default=0.28)
    parser.add_argument('--silent', action='store_true', help='Disable default film-change sound')
    opt = parser.parse_args()
    if not all(1 <= n <= 8192 for n in [opt.width, opt.height]) or opt.width % 2 or opt.height % 2:
        parser.error('Width/height must be positive even integers up to 8192')
    if opt.fps not in [24, 25, 30, 50, 60] or min(opt.hold_frames, opt.last_hold_frames) < 1:
        parser.error('Invalid fps or frame hold')
    if not math.isfinite(opt.fisheye) or not 0 <= opt.fisheye <= 1.2 or not 0 <= opt.blur <= 8:
        parser.error('Fisheye must be 0..1.2 and blur 0..8')
    if opt.keyword_height is not None and (not math.isfinite(opt.keyword_height) or opt.keyword_height <= 0):
        parser.error('Keyword height must be positive and finite')
    if not math.isfinite(opt.sfx_gain) or not 0 <= opt.sfx_gain <= 1:
        parser.error('SFX gain must be 0..1')
    if opt.out.exists():
        parser.error(f'Output already exists: {opt.out}; use a new directory')
    if not opt.gsap.is_file():
        parser.error('Supply a real local gsap.min.js file')
    data = json.loads(opt.manifest.read_text())
    captures = data.get('captures', [])
    if not data.get('keyword') or not captures:
        parser.error('Manifest requires keyword and at least one successful capture')
    images, seen = [], set()
    for entry in captures:
        if entry.get('selected_text') != data['keyword']:
            parser.error(f"Capture {entry.get('id')} does not match the actual keyword")
        if not entry.get('url', '').startswith(('http://', 'https://')):
            parser.error('Every capture needs a real HTTP(S) source URL')
        source_path = opt.manifest.parent / entry['image']
        image = Image.open(source_path).convert('RGB')
        if image.size != (entry['image_width'], entry['image_height']):
            parser.error(f'Screenshot dimensions mismatch: {source_path}')
        box = entry['keyword_box']
        if any(not isinstance(box.get(k), (float, int)) or not math.isfinite(box[k]) for k in ['x', 'y', 'width', 'height']):
            parser.error('Keyword box must contain finite pixel coordinates')
        if min(box['x'], box['y']) < 0 or min(box['width'], box['height']) <= 0 \
                or box['x'] + box['width'] > image.width or box['y'] + box['height'] > image.height:
            parser.error(f'Invalid keyword box: {source_path}')
        fingerprint = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if fingerprint in seen:
            parser.error('Duplicate screenshot; do not imply distinct sources with repeated captures')
        seen.add(fingerprint)
        images.append(image)
    target = opt.keyword_height or min(opt.width, opt.height) * 0.07
    target = min(target, *(opt.width * 0.7 * e['keyword_box']['height'] / e['keyword_box']['width'] for e in captures))
    assets = opt.out / 'assets'
    assets.mkdir(parents=True)
    originals = opt.out / 'originals'
    originals.mkdir()
    source_records = json.loads(json.dumps(data))
    for i, entry in enumerate(captures):
        relative = f'originals/source-{i + 1:03}.png'
        shutil.copyfile(opt.manifest.parent / entry['image'], opt.out / relative)
        source_records['captures'][i]['image'] = relative
    shutil.copyfile(opt.gsap, assets / 'gsap.min.js')
    clips, timings, thumbnails = [], [], []
    frame_cursor = 0
    for i, (entry, image) in enumerate(zip(captures, images)):
        result = align_frame(image, entry['keyword_box'], opt.width, opt.height, target, opt.fisheye, opt.blur)
        relative = f'assets/frame-{i + 1:03}.png'
        result.save(opt.out / relative)
        thumb = result.copy()
        thumb.thumbnail((270, 270))
        thumbnails.append(thumb)
        hold = opt.last_hold_frames if i == len(captures) - 1 else opt.hold_frames
        start, duration = frame_cursor / opt.fps, hold / opt.fps
        clips.append(f'<img id="frame-{i + 1}" class="clip" data-start="{start:.9f}" data-duration="{duration:.9f}" data-track-index="0" src="{relative}" alt="{html.escape(data["keyword"], quote=True)}" />')
        timings.append({'source_id': entry['id'], 'url': entry['url'], 'image': relative,
                        'start_frame': frame_cursor, 'frames': hold, 'start': start, 'duration': duration})
        frame_cursor += hold
    duration = frame_cursor / opt.fps
    audio_meta = None
    if not opt.silent and len(captures) > 1:
        audio_meta = write_cut_audio(assets, timings, frame_cursor, opt.fps, opt.sfx, opt.sfx_gain)
        clips.append(f'<audio id="film-change-audio" src="assets/film-changes.wav" data-start="0" data-duration="{duration:.9f}" data-track-index="1" data-volume="1"></audio>')
    title = html.escape(f'text-match-cut — {data["keyword"]}')
    document = f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><title>{title}</title>
<script src="assets/gsap.min.js"></script>
<style>html,body{{margin:0;background:#fff;}}#root{{position:relative;width:100%;height:100%;overflow:hidden;}}
.clip{{position:absolute;inset:0;display:block;width:100%;height:100%;object-fit:fill;}}</style>
</head><body><div id="root" data-composition-id="text-match-cut" data-start="0" data-width="{opt.width}" data-height="{opt.height}" data-fps="{opt.fps}" data-duration="{duration:.9f}">
{chr(10).join(clips)}
</div><script>
const tl = gsap.timeline({{paused:true}});
const clock = {{progress:0}};
tl.to(clock, {{progress:1, duration:{duration:.9f}, ease:"none"}}, 0);
window.__timelines["text-match-cut"] = tl;
</script></body></html>'''
    (opt.out / 'index.html').write_text(document)
    (opt.out / 'hyperframes.json').write_text(json.dumps({'fps': opt.fps}, indent=2))
    (opt.out / 'sources.json').write_text(json.dumps(source_records, ensure_ascii=False, indent=2))
    summary = {'keyword': data['keyword'], 'width': opt.width, 'height': opt.height, 'fps': opt.fps,
               'fisheye': opt.fisheye, 'peripheral_blur': opt.blur, 'keyword_height': target,
               'keyword_center': [opt.width / 2, opt.height / 2], 'total_frames': frame_cursor,
               'duration': duration, 'audio': audio_meta, 'clips': timings}
    (opt.out / 'composition.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    columns = min(4, len(thumbnails))
    sheet = Image.new('RGB', (columns * 290, math.ceil(len(thumbnails) / columns) * 305), '#e5e5e5')
    draw = ImageDraw.Draw(sheet)
    for i, thumb in enumerate(thumbnails):
        x, y = (i % columns) * 290, (i // columns) * 305
        sheet.paste(thumb, (x + (290 - thumb.width) // 2, y + 25))
        draw.text((x + 10, y + 5), f'{i + 1:02} | frame {timings[i]["start_frame"]}', fill='#222')
    sheet.save(opt.out / 'contact-sheet.jpg', quality=92)
    print(json.dumps({'project': str(opt.out.resolve()), 'captures': len(captures),
                      'duration': duration, 'frames': frame_cursor, 'fisheye': opt.fisheye}))


if __name__ == '__main__':
    main()
